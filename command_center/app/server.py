"""
Jojo1 Command Center — FastAPI backend.
Proxy naar control_api + Market Oracle met eigen auth, audit logging en rate limiting.
"""

import os
import time
import json
import sqlite3
import secrets
import random
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from contextlib import contextmanager

import requests
from fastapi import FastAPI, HTTPException, Request, Header, Query, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ── Config ──────────────────────────────────────────────────────────────────

CONTROL_API_URL       = os.environ.get("CONTROL_API_URL", "http://control_api:8080")
INDICATOR_ENGINE_URL  = os.environ.get("INDICATOR_ENGINE_URL", "http://indicator_engine:8099")
CONTROL_API_TOKEN = os.environ.get("CONTROL_API_TOKEN", "")
TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
ORACLE_URL = os.environ.get("ORACLE_URL", "http://market_oracle_sandbox:8095")
DB_PATH = "/var/command_center/cc.db"
AUDIT_LOG_PATH = "/var/command_center/audit.log"
SESSION_TTL_HOURS = 8
OTP_TTL_MINUTES = 10
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 600  # 10 min

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("command_center")

audit_logger = logging.getLogger("audit")
audit_handler = logging.FileHandler(AUDIT_LOG_PATH)
audit_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
audit_logger.addHandler(audit_handler)
audit_logger.setLevel(logging.INFO)

# ── Database ────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS otp_codes (
            email TEXT, code TEXT, expires_at TEXT, created_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, email TEXT, expires_at TEXT, created_at TEXT
        )""")


init_db()

# ── Rate limiting (in-memory) ──────────────────────────────────────────────

_login_attempts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str):
    now = time.time()
    attempts = _login_attempts[ip]
    # Prune old entries
    _login_attempts[ip] = [t for t in attempts if now - t < LOGIN_WINDOW_SECONDS]
    if len(_login_attempts[ip]) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Te veel loginpogingen. Probeer over 10 minuten opnieuw.")
    _login_attempts[ip].append(now)


# ── Auth helpers ────────────────────────────────────────────────────────────

def _audit(action: str, user: str, ip: str, result: str, detail: str = ""):
    msg = f"user={user} | ip={ip} | action={action} | result={result}"
    if detail:
        msg += f" | {detail}"
    audit_logger.info(msg)


def _validate_session(token: str | None) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Niet ingelogd")
    # Strip "Bearer " prefix if present
    if token.startswith("Bearer "):
        token = token[7:]
    with get_db() as conn:
        row = conn.execute(
            "SELECT email, expires_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Ongeldige sessie")
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Sessie verlopen")
    return row["email"]


def _proxy_get(path: str, params: dict | None = None) -> dict:
    """GET naar control_api met auth header."""
    try:
        r = requests.get(
            f"{CONTROL_API_URL}{path}",
            headers={"X-API-KEY": CONTROL_API_TOKEN},
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"control_api onbereikbaar: {e}")


def _proxy_post(path: str, body: dict | None = None, headers: dict | None = None) -> dict:
    """POST naar control_api met auth header."""
    hdrs = {"X-API-KEY": CONTROL_API_TOKEN, "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    try:
        r = requests.post(
            f"{CONTROL_API_URL}{path}",
            headers=hdrs,
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        # Forward status code from control_api
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"control_api onbereikbaar: {e}")


# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="Jojo1 Command Center", docs_url=None, redoc_url=None)

# Security headers middleware
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'"
    )
    return response


# ── Auth endpoints ──────────────────────────────────────────────────────────

class OTPRequest(BaseModel):
    email: str

class OTPVerify(BaseModel):
    email: str
    code: str


@app.post("/cc/auth/request")
async def auth_request(body: OTPRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    if ALLOWED_EMAIL and body.email != ALLOWED_EMAIL:
        _audit("login_request", body.email, ip, "denied", "email not allowed")
        raise HTTPException(status_code=403, detail="Email niet toegestaan")

    code = str(random.randint(100000, 999999))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()

    with get_db() as conn:
        conn.execute("DELETE FROM otp_codes WHERE email = ?", (body.email,))
        conn.execute(
            "INSERT INTO otp_codes (email, code, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (body.email, code, expires, datetime.now(timezone.utc).isoformat()),
        )

    # Stuur OTP via Telegram
    if TG_BOT_TOKEN and TG_CHAT_ID:
        msg = f"Command Center login code: `{code}`\nGeldig voor {OTP_TTL_MINUTES} minuten."
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            log.error(f"Telegram OTP send failed: {e}")

    _audit("login_request", body.email, ip, "otp_sent")
    return {"ok": True, "message": "Code verstuurd via Telegram"}


@app.post("/cc/auth/verify")
async def auth_verify(body: OTPVerify, request: Request):
    ip = request.client.host if request.client else "unknown"

    with get_db() as conn:
        row = conn.execute(
            "SELECT code, expires_at FROM otp_codes WHERE email = ? ORDER BY rowid DESC LIMIT 1",
            (body.email,),
        ).fetchone()

    if not row:
        _audit("login_verify", body.email, ip, "denied", "no otp found")
        raise HTTPException(status_code=401, detail="Geen code gevonden")

    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        with get_db() as conn:
            conn.execute("DELETE FROM otp_codes WHERE email = ?", (body.email,))
        _audit("login_verify", body.email, ip, "denied", "code expired")
        raise HTTPException(status_code=401, detail="Code verlopen")

    if row["code"] != body.code:
        _audit("login_verify", body.email, ip, "denied", "wrong code")
        raise HTTPException(status_code=401, detail="Onjuiste code")

    # Create session
    token = secrets.token_hex(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)).isoformat()

    with get_db() as conn:
        conn.execute("DELETE FROM otp_codes WHERE email = ?", (body.email,))
        conn.execute(
            "INSERT INTO sessions (token, email, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, body.email, expires, datetime.now(timezone.utc).isoformat()),
        )

    _audit("login_verify", body.email, ip, "success")
    return {"ok": True, "token": token, "expires_at": expires}


@app.post("/cc/auth/logout")
async def auth_logout(request: Request, authorization: str | None = Header(None)):
    token = authorization
    if token and token.startswith("Bearer "):
        token = token[7:]
    if token:
        with get_db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    return {"ok": True}


# ── Status endpoint ─────────────────────────────────────────────────────────

@app.get("/cc/status")
async def cc_status(request: Request, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    data = _proxy_get("/status")
    _audit("view_status", email, request.client.host if request.client else "?", "ok")
    return data


# ── Proposals ───────────────────────────────────────────────────────────────

@app.get("/cc/proposals")
async def cc_proposals(
    request: Request,
    state: str = Query("pending"),
    authorization: str | None = Header(None),
):
    email = _validate_session(authorization)
    data = _proxy_get("/proposals/v2", params={"state": state})
    _audit("view_proposals", email, request.client.host if request.client else "?", "ok", f"state={state}")
    return data


@app.post("/cc/proposals/{proposal_id}/confirm")
async def cc_confirm(
    proposal_id: str,
    request: Request,
    authorization: str | None = Header(None),
    x_otp: str | None = Header(None),
):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"

    if not x_otp:
        raise HTTPException(status_code=400, detail="X-OTP header vereist")

    result = _proxy_post(
        f"/proposals/{proposal_id}/confirm",
        headers={"X-OTP": x_otp},
    )
    _audit("confirm_proposal", email, ip, "confirmed", f"proposal={proposal_id}")
    return result


class RejectBody(BaseModel):
    reason: str = ""

@app.post("/cc/proposals/{proposal_id}/reject")
async def cc_reject(
    proposal_id: str,
    body: RejectBody,
    request: Request,
    authorization: str | None = Header(None),
):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    # Control_api has no reject endpoint yet — log it and update local state
    _audit("reject_proposal", email, ip, "rejected", f"proposal={proposal_id} reason={body.reason}")
    return {"ok": True, "proposal_id": proposal_id, "status": "rejected", "reason": body.reason}


# ── Trading controls ────────────────────────────────────────────────────────

class PauseBody(BaseModel):
    minutes: int = 30
    reason: str = ""

@app.post("/cc/pause")
async def cc_pause(body: PauseBody, request: Request, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    result = _proxy_post("/trading/pause", {"minutes": body.minutes, "reason": body.reason})
    _audit("pause_trading", email, ip, "ok", f"minutes={body.minutes} reason={body.reason}")
    return result


@app.post("/cc/resume")
async def cc_resume(request: Request, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    result = _proxy_post("/trading/resume")
    _audit("resume_trading", email, ip, "ok")
    return result


# ── Backtest ────────────────────────────────────────────────────────────────

@app.get("/cc/backtest/{symbol}")
async def cc_backtest(
    symbol: str,
    request: Request,
    interval: str = Query("1h"),
    months: int = Query(3),
    authorization: str | None = Header(None),
):
    email = _validate_session(authorization)
    data = _proxy_get(f"/backtest/historical/{symbol}", params={"interval": interval, "months": months})
    _audit("run_backtest", email, request.client.host if request.client else "?", "ok", f"symbol={symbol}")
    return data


# ── Balance ─────────────────────────────────────────────────────────────────

@app.get("/cc/balance")
async def cc_balance(request: Request, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    return _proxy_get("/balance")


# ── Oracle ──────────────────────────────────────────────────────────────────

@app.get("/cc/oracle")
async def cc_oracle(request: Request, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    try:
        r = requests.get(f"{ORACLE_URL}/scan", timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Market Oracle onbereikbaar: {e}")
    _audit("oracle_scan", email, ip, "ok")
    return data


# ── Logs ────────────────────────────────────────────────────────────────────

@app.get("/cc/logs")
async def cc_logs(
    request: Request,
    level: str = Query(""),
    limit: int = Query(100),
    authorization: str | None = Header(None),
):
    email = _validate_session(authorization)
    limit = min(limit, 500)

    lines = []
    if os.path.exists(AUDIT_LOG_PATH):
        with open(AUDIT_LOG_PATH, "r") as f:
            all_lines = f.readlines()
        # Filter by level if specified
        if level:
            level_upper = level.upper()
            lines = [l.strip() for l in all_lines if level_upper in l.upper()]
        else:
            lines = [l.strip() for l in all_lines]
        lines = lines[-limit:]

    return {"lines": lines, "total": len(lines), "level_filter": level}


# ── Indicator Engine proxy (read-only, geen extra auth nodig) ────────────────

def _ie_get(path: str, params: dict = None):
    try:
        r = requests.get(f"{INDICATOR_ENGINE_URL}{path}", params=params, timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(502, f"indicator_engine onbereikbaar: {e}")


@app.get("/cc/mode/current")
async def cc_mode_current(request: Request, authorization: str | None = Header(None)):
    _validate_session(authorization)
    return _ie_get("/mode/current")


@app.get("/cc/mode/log")
async def cc_mode_log(request: Request, limit: int = 50, authorization: str | None = Header(None)):
    _validate_session(authorization)
    return _ie_get("/mode/log", {"limit": limit})


@app.get("/cc/short/status")
async def cc_short_status(request: Request, authorization: str | None = Header(None)):
    _validate_session(authorization)
    return _ie_get("/short/status")


@app.get("/cc/short/log")
async def cc_short_log(request: Request, since: str = None, limit: int = 100, authorization: str | None = Header(None)):
    _validate_session(authorization)
    params = {"limit": limit}
    if since:
        params["since"] = since
    return _ie_get("/short/log", params)


@app.get("/cc/alerts/high-impact")
async def cc_alerts(
    request: Request,
    severity: str = None,
    kind: str = None,
    limit: int = 50,
    since: str = None,
    authorization: str | None = Header(None),
):
    _validate_session(authorization)
    params = {"limit": limit}
    if severity:
        params["severity"] = severity
    if kind:
        params["kind"] = kind
    if since:
        params["since"] = since
    return _ie_get("/alerts/high-impact", params)


# ── Universe ─────────────────────────────────────────────────────────────────

@app.get("/cc/universe/current")
async def cc_universe_current(request: Request, authorization: str | None = Header(None)):
    """Huidig coin-universe: trading coins + stablecoins."""
    _validate_session(authorization)
    return _ie_get("/universe/current")


@app.post("/cc/universe/refresh")
async def cc_universe_refresh(request: Request, authorization: str | None = Header(None)):
    """Trigger handmatige universe refresh."""
    email = _validate_session(authorization)
    ip    = request.client.host if request.client else "?"
    result = _ie_post("/universe/refresh")
    _audit("universe_refresh", email, ip, "ok")
    return result


@app.get("/cc/universe/history")
async def cc_universe_history(
    request: Request,
    days: int = 7,
    authorization: str | None = Header(None),
):
    """Universe refresh geschiedenis."""
    _validate_session(authorization)
    return _ie_get("/universe/history", {"days": days})


@app.get("/cc/realtime/health")
async def cc_realtime_health(request: Request, authorization: str | None = Header(None)):
    _validate_session(authorization)
    return _ie_get("/realtime/health")


@app.get("/cc/short/replay/jobs")
async def cc_replay_jobs(request: Request, authorization: str | None = Header(None)):
    _validate_session(authorization)
    return _ie_get("/short/replay/jobs")


@app.get("/cc/short/replay/result/{job_id}")
async def cc_replay_result(request: Request, job_id: str, authorization: str | None = Header(None)):
    _validate_session(authorization)
    return _ie_get(f"/short/replay/result/{job_id}")


# ── Indicator Engine actions (met 2-step confirm + audit) ────────────────────

class ConfirmedAction(BaseModel):
    reason: str = ""
    confirm: str = ""   # moet "CONFIRM" zijn


def _ie_post(path: str, params: dict = None):
    try:
        r = requests.post(f"{INDICATOR_ENGINE_URL}{path}", params=params, timeout=5)
        return r.json()
    except Exception as e:
        raise HTTPException(502, f"indicator_engine onbereikbaar: {e}")


@app.post("/cc/mode/reset")
async def cc_mode_reset(request: Request, body: ConfirmedAction, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    if body.confirm != "CONFIRM":
        raise HTTPException(400, "Bevestiging vereist: confirm='CONFIRM'")
    result = _ie_post("/mode/reset", {"reason": body.reason or "Dashboard reset"})
    _audit("mode_reset", email, ip, "ok", body.reason or "geen reden")
    return result


@app.post("/cc/short/enable")
async def cc_short_enable(request: Request, body: ConfirmedAction, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    if body.confirm != "CONFIRM":
        raise HTTPException(400, "Bevestiging vereist")
    result = _ie_post("/short/enable", {"reason": body.reason or "Dashboard actie"})
    _audit("short_enable", email, ip, "ok", body.reason or "geen reden")
    return result


@app.post("/cc/short/disable")
async def cc_short_disable(request: Request, body: ConfirmedAction, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    if body.confirm != "CONFIRM":
        raise HTTPException(400, "Bevestiging vereist")
    result = _ie_post("/short/disable", {"reason": body.reason or "Dashboard actie"})
    _audit("short_disable", email, ip, "ok", body.reason or "geen reden")
    return result


class ReplayRunBody(BaseModel):
    symbol:        str   = "BTCUSDT"
    days:          int   = 90
    sweep:         bool  = False
    delta_thr:     float = -1.5
    vol_ratio_thr: float = 1.8
    trail_pct:     float = 1.0
    confirm:       str   = ""


@app.post("/cc/short/replay/run")
async def cc_replay_run(request: Request, body: ReplayRunBody, authorization: str | None = Header(None)):
    email = _validate_session(authorization)
    ip = request.client.host if request.client else "unknown"
    if body.confirm != "CONFIRM":
        raise HTTPException(400, "Bevestiging vereist")
    try:
        r = requests.post(
            f"{INDICATOR_ENGINE_URL}/short/replay/run",
            json=body.model_dump(exclude={"confirm"}),
            timeout=10,
        )
        result = r.json()
    except Exception as e:
        raise HTTPException(502, str(e))
    _audit("replay_run", email, ip, "ok", f"symbol={body.symbol} days={body.days} sweep={body.sweep}")
    return result


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/cc/health")
async def health():
    return {"status": "ok", "service": "command_center"}


# ── Static files (login + dashboard) ───────────────────────────────────────

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/dashboard")
async def dashboard():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
