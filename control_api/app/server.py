import os, json, requests, secrets, random, time, logging
import asyncio
import numpy as np
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from db_compat import get_conn, dict_cursor, adapt_query, is_pg
import testbot as _tb

DB_PATH = "/var/apex/apex.db"  # fallback for SQLite mode
STATE_PATH = "/var/apex/bot_state.json"
LOG_PATH = "/var/apex/control_api.log"

# File logging zodat Jojo1 logs kan uitlezen via /admin/logs
log = logging.getLogger("control_api")
log.setLevel(logging.INFO)
_fh = logging.FileHandler(LOG_PATH)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
log.info("control_api gestart")
TOKEN = os.getenv("CONTROL_API_TOKEN", "")

# Telegram auth configuratie
TG_BOT_TOKEN   = os.getenv("TG_BOT_TOKEN_COORDINATOR", "")
TG_CHAT_ID     = os.getenv("TG_CHAT_ID", "")
ALLOWED_EMAILS = [e.strip() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()]

def ensure_auth_tables(conn):
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS otp_codes(
        email TEXT NOT NULL,
        code TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS sessions(
        token TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""")
    conn.commit()

def auth(x_api_key: str | None):
    if not TOKEN:
        raise RuntimeError("CONTROL_API_TOKEN missing")
    if x_api_key == TOKEN:
        return  # static API key OK
    # Check session token
    if x_api_key:
        conn = get_conn()
        ensure_auth_tables(conn)
        cur = conn.cursor()
        cur.execute(adapt_query("SELECT expires_at FROM sessions WHERE token=?"), (x_api_key,))
        row = cur.fetchone()
        conn.close()
        if row:
            exp = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(row[0])
            if datetime.now(timezone.utc) < exp:
                return  # valid session
    raise HTTPException(status_code=401, detail="Unauthorized")

app = FastAPI(title="Control API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        resp = await call_next(request)
        if request.url.path not in ("/health", "/docs", "/openapi.json"):
            log.info(f"{request.method} {request.url.path} → {resp.status_code}")
        return resp

app.add_middleware(RequestLogMiddleware)

class Proposal(BaseModel):
    agent: str
    params: dict
    reason: str = ""

class AuthRequest(BaseModel):
    email: str

class AuthVerify(BaseModel):
    email: str
    code: str

@app.post("/auth/request")
def auth_request(body: AuthRequest):
    email = body.email.strip().lower()
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        raise HTTPException(status_code=403, detail="E-mailadres niet toegestaan")
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        raise HTTPException(status_code=500, detail="Telegram niet geconfigureerd")

    code = str(random.randint(100000, 999999))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    conn = get_conn()
    ensure_auth_tables(conn)
    cur = conn.cursor()
    # Verwijder oude codes voor dit email
    cur.execute(adapt_query("DELETE FROM otp_codes WHERE email=?"), (email,))
    cur.execute(adapt_query("INSERT INTO otp_codes(email, code, expires_at) VALUES (?,?,?)"), (email, code, expires))
    conn.commit()
    conn.close()

    msg = f"🔐 OpenClaw Login Code\n\nJouw code: *{code}*\n\nGeldig voor 10 minuten."
    r = requests.post(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
        timeout=10
    )
    if not r.ok:
        raise HTTPException(status_code=500, detail="Telegram bericht mislukt")

    return {"ok": True, "message": "Code verstuurd via Telegram"}

@app.post("/auth/verify")
def auth_verify(body: AuthVerify):
    email = body.email.strip().lower()
    code  = body.code.strip()

    conn = get_conn()
    ensure_auth_tables(conn)
    cur  = conn.cursor()
    cur.execute(adapt_query("SELECT code, expires_at FROM otp_codes WHERE email=? ORDER BY code DESC LIMIT 1"), (email,))
    row = cur.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Geen code aangevraagd")

    stored_code, expires_at = row[0], row[1]
    if datetime.fromisoformat(str(expires_at)) < datetime.now(timezone.utc):
        cur.execute(adapt_query("DELETE FROM otp_codes WHERE email=?"), (email,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=401, detail="Code verlopen")

    if stored_code != code:
        conn.close()
        raise HTTPException(status_code=401, detail="Onjuiste code")

    # Code correct → maak sessie aan (24 uur)
    token    = secrets.token_hex(32)
    sess_exp = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    cur.execute(adapt_query("DELETE FROM otp_codes WHERE email=?"), (email,))
    cur.execute(adapt_query("INSERT INTO sessions(token, email, expires_at) VALUES (?,?,?)"), (token, email, sess_exp))
    conn.commit()
    conn.close()

    return {"ok": True, "token": token, "expires_at": sess_exp}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/state/latest")
def state_latest(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

@app.get("/signal-performance")
def signal_performance(limit: int = 50, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Terugkijken: wat had elk signaal opgeleverd als je het had gevolgd?"""
    auth(x_api_key)
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(adapt_query("""
            SELECT id, ts, symbol, signal, active_signals,
                   entry_price, price_15m, price_1h, price_4h,
                   pnl_15m_pct, pnl_1h_pct, pnl_4h_pct, status
            FROM signal_performance
            ORDER BY id DESC LIMIT ?
        """), (limit,))
        rows = cur.fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "id": r[0], "ts": r[1], "symbol": r[2], "signal": r[3],
                "active_signals": json.loads(r[4] or "[]"),
                "entry_price": r[5],
                "price_15m": r[6], "price_1h": r[7], "price_4h": r[8],
                "pnl_15m_pct": r[9], "pnl_1h_pct": r[10], "pnl_4h_pct": r[11],
                "status": r[12],
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def ensure_tables(conn):
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS proposals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        agent TEXT NOT NULL,
        params_json TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
    )""")
    conn.commit()

@app.get("/proposals")
def list_proposals(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    conn = get_conn()
    ensure_tables(conn)
    cur = conn.cursor()
    cur.execute("SELECT id, ts, agent, params_json, reason, status FROM proposals ORDER BY id DESC LIMIT 200")
    rows = cur.fetchall()
    conn.close()
    return [{"id":r[0],"ts":r[1],"agent":r[2],"params":json.loads(r[3]),"reason":r[4],"status":r[5]} for r in rows]

@app.post("/config/propose")
def propose(p: Proposal, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    conn = get_conn()
    ensure_tables(conn)
    cur = conn.cursor()
    ts = datetime.now(timezone.utc).isoformat()
    cur.execute(adapt_query("INSERT INTO proposals(ts, agent, params_json, reason, status) VALUES (?, ?, ?, ?, 'pending')"),
                (ts, p.agent, json.dumps(p.params, ensure_ascii=False), p.reason))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return {"ok": True, "proposal_id": pid}

@app.post("/proposals/{proposal_id}/apply")
def apply_proposal(proposal_id: int, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    conn = get_conn()
    ensure_tables(conn)
    cur = conn.cursor()
    # Lees proposal data voor executie
    cur.execute(adapt_query("SELECT agent, params_json, reason, status FROM proposals WHERE id=?"), (proposal_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Proposal niet gevonden")
    agent, params_json, reason, status = row[0], row[1], row[2], row[3]
    if status == "applied":
        conn.close()
        return {"ok": True, "applied": proposal_id, "message": "Al uitgevoerd"}
    # Update status
    cur.execute(adapt_query("UPDATE proposals SET status='applied' WHERE id=?"), (proposal_id,))
    conn.commit()
    conn.close()
    # Voer de parameter wijziging daadwerkelijk uit
    try:
        params = json.loads(params_json) if isinstance(params_json, str) else (params_json or {})
    except (json.JSONDecodeError, TypeError):
        params = {}
    if params:
        _execute_proposal(str(proposal_id), "PARAM_CHANGE", params, reason or "")
    return {"ok": True, "applied": proposal_id, "executed": True}


@app.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: int, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    conn = get_conn()
    ensure_tables(conn)
    cur = conn.cursor()
    cur.execute(adapt_query("SELECT status FROM proposals WHERE id=?"), (proposal_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Proposal niet gevonden")
    if row[0] == "applied":
        conn.close()
        raise HTTPException(status_code=400, detail="Proposal is al uitgevoerd, kan niet meer afgewezen worden")
    cur.execute(adapt_query("UPDATE proposals SET status='rejected' WHERE id=?"), (proposal_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "rejected": proposal_id}


@app.get("/backtest/{symbol}")
def backtest(symbol: str, interval: str = "1h", limit: int = 500,
             x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    try:
        import talib
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        close  = np.array([float(c[4]) for c in data])
        high   = np.array([float(c[2]) for c in data])
        low    = np.array([float(c[3]) for c in data])

        rsi          = talib.RSI(close, 14)
        _, _, hist   = talib.MACD(close, 12, 26, 9)
        ema20        = talib.EMA(close, 20)
        ema50        = talib.EMA(close, 50)

        fee    = 6 / 10000
        trades = []
        pos    = None

        for i in range(50, len(close)):
            if any(np.isnan(x[i]) for x in [rsi, hist, ema20, ema50]):
                continue
            price = close[i]
            if pos is None and rsi[i] < 45 and hist[i] > 0:
                pos = price
            elif pos is not None and (rsi[i] > 60 or price < pos * 0.97):
                pnl = (price / pos - 1) - 2 * fee
                trades.append(round(pnl * 100, 4))
                pos = None

        if not trades:
            return {"symbol": symbol, "trades": 0}

        wins   = [p for p in trades if p > 0]
        losses = [abs(p) for p in trades if p <= 0]
        arr    = np.array(trades)
        eq     = np.cumsum(arr)
        peak   = np.maximum.accumulate(eq)

        return {
            "symbol":           symbol,
            "interval":         interval,
            "bars":             len(close),
            "trades":           len(trades),
            "win_rate":         round(len(wins) / len(trades) * 100, 2),
            "profit_factor":    round(sum(wins) / sum(losses), 3) if losses else 999.0,
            "max_drawdown_pct": round(float(np.max(peak - eq)), 4),
            "sharpe":           round(float(np.mean(arr) / np.std(arr) * np.sqrt(len(arr))), 3)
                                if np.std(arr) > 0 else 0.0,
            "total_return_pct": round(float(sum(trades)), 4),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Historische Backtest (6 maanden) ────────────────────────────────────────

def _ensure_hist_table(conn):
    cur = conn.cursor()
    cur.execute(adapt_query("""CREATE TABLE IF NOT EXISTS historical_backtest(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_ts TEXT NOT NULL,
        symbol TEXT NOT NULL,
        interval TEXT NOT NULL,
        months INTEGER NOT NULL,
        candle_ts TEXT NOT NULL,
        signal TEXT NOT NULL,
        active_signals TEXT,
        entry_price REAL NOT NULL,
        price_1h REAL,
        price_4h REAL,
        price_24h REAL,
        pnl_1h_pct REAL,
        pnl_4h_pct REAL,
        pnl_24h_pct REAL
    )"""))
    conn.commit()

def _fetch_klines_paginated(symbol: str, interval: str, months: int) -> list:
    """
    Haal historische klines op van Binance.
    months=0  → alles wat beschikbaar is (MAX, bijv. BTC terug tot 2017)
    months>0  → terug tot `months` maanden
    """
    end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=months * 30)).timestamp() * 1000) \
               if months > 0 else 0
    all_data = []
    batch_ms = end_ms
    max_batches = 500  # veiligheidsgrens (500 × 1000 = 500 000 candles)

    for _ in range(max_batches):
        params = {
            "symbol":    symbol.upper(),
            "interval":  interval,
            "endTime":   batch_ms,
            "limit":     1000,
        }
        r = requests.get("https://api.binance.com/api/v3/klines", params=params, timeout=20)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        all_data = batch + all_data  # prepend (oudste eerst)
        oldest_open = batch[0][0]
        # Stop als we de gewenste startdatum bereikt hebben
        if months > 0 and oldest_open <= start_ms:
            break
        # Stop als Binance < 1000 candles teruggaf (begin van beschikbare data)
        if len(batch) < 1000:
            break
        batch_ms = oldest_open - 1
        time.sleep(0.15)  # Binance rate limit

    # Trim naar start_ms als van toepassing
    if months > 0:
        all_data = [c for c in all_data if c[0] >= start_ms]
    return all_data

def _run_hist_signals(klines: list, symbol: str, interval: str, months: int, run_ts: str) -> dict:
    """Draai alle 5 strategieën over historische data en evalueer elk signaal."""
    try:
        import talib
    except ImportError:
        raise RuntimeError("talib niet beschikbaar")

    o = np.array([float(c[1]) for c in klines])
    h = np.array([float(c[2]) for c in klines])
    l = np.array([float(c[3]) for c in klines])
    c = np.array([float(c[4]) for c in klines])
    v = np.array([float(c[5]) for c in klines])
    ts_arr = [int(k[0]) for k in klines]

    # Indicatoren over de volledige reeks
    rsi       = talib.RSI(c, 14)
    macd, macd_sig, macd_hist = talib.MACD(c, 12, 26, 9)
    ema21     = talib.EMA(c, 21)
    ema55     = talib.EMA(c, 55)
    ema200    = talib.EMA(c, 200)
    adx       = talib.ADX(h, l, c, 14)
    plus_di   = talib.PLUS_DI(h, l, c, 14)
    minus_di  = talib.MINUS_DI(h, l, c, 14)
    bb_u, bb_m, bb_l = talib.BBANDS(c, 20, 2, 2)
    bb_width  = (bb_u - bb_l) / bb_m * 100
    stk, std  = talib.STOCHRSI(c, 14, 3, 3)
    atr_arr   = talib.ATR(h, l, c, 14)
    vol_sma   = talib.SMA(v, 20)

    # Wick filter
    wick      = np.where(atr_arr > 0,
                         np.maximum(h - np.maximum(o, c), np.minimum(o, c) - l) / atr_arr, 0)

    # Aantal candles per tijdstap afhankelijk van interval
    interval_hours = {"1h": 1, "4h": 4, "1d": 24, "15m": 0.25, "5m": 1/12}.get(interval, 1)
    step_1h  = max(1, round(1  / interval_hours))
    step_4h  = max(1, round(4  / interval_hours))
    step_24h = max(1, round(24 / interval_hours))

    signals_found = []
    lookback = 210  # minimaal nodig voor ema200

    for i in range(lookback, len(c) - step_24h):
        if any(np.isnan(x) for x in [rsi[i], macd_hist[i], ema21[i], ema55[i], adx[i]]):
            continue

        price = c[i]
        _rsi      = rsi[i]
        _mh       = macd_hist[i]
        _macd     = macd[i]
        _msig     = macd_sig[i]
        _e21      = ema21[i]
        _e55      = ema55[i]
        _e200     = ema200[i]
        _adx      = adx[i]
        _pdi      = plus_di[i]
        _mdi      = minus_di[i]
        _bbw      = bb_width[i]
        _bbu      = bb_u[i]
        _bbl      = bb_l[i]
        _sk       = stk[i]
        _sd       = std[i]
        _wick_ok  = (wick[i] < 0.6) if not np.isnan(wick[i]) else True
        _vsma     = vol_sma[i] if not np.isnan(vol_sma[i]) else 0

        # Strategie condities
        rsi_macd_long = _rsi < 32 and _mh > 0 and _macd > _msig and _wick_ok
        squeeze       = _bbw < 2.5
        bb_long       = squeeze and price > _bbu
        golden_cross  = _e21 > _e55 > _e200
        srsi_long     = not np.isnan(_sk) and _sk < 20 and _sk > _sd and _rsi < 45
        adx_long      = _adx > 25 and _pdi > _mdi

        perfect_day   = rsi_macd_long and (bb_long or squeeze) and (golden_cross or _e21 > _e55) and adx_long
        breakout_bull = price > _bbu and _rsi > 50 and v[i] > _vsma * 1.5
        momentum_cont = golden_cross and 50 < _rsi < 65 and _mh > 0 and adx_long

        if perfect_day:
            sig = "PERFECT_DAY"
        elif breakout_bull:
            sig = "BREAKOUT_BULL"
        elif momentum_cont:
            sig = "MOMENTUM"
        elif rsi_macd_long or bb_long or golden_cross or srsi_long or adx_long:
            sig = "BUY"
        else:
            continue  # geen koopsignaal → overslaan

        active = []
        if rsi_macd_long:  active.append("RSI-MACD")
        if bb_long:        active.append("BB-Squeeze")
        if golden_cross:   active.append("GoldenCross")
        if srsi_long:      active.append("StochRSI")
        if adx_long:       active.append("ADX")
        if perfect_day:    active.append("⭐PerfectDay")
        if breakout_bull:  active.append("Breakout")
        if momentum_cont:  active.append("Momentum")

        # Toekomstige prijzen (vooruitkijken)
        p1h  = float(c[i + step_1h])
        p4h  = float(c[i + step_4h])  if i + step_4h  < len(c) else p1h
        p24h = float(c[i + step_24h]) if i + step_24h < len(c) else p4h

        candle_dt = datetime.fromtimestamp(ts_arr[i] / 1000, tz=timezone.utc).isoformat()

        signals_found.append({
            "run_ts":       run_ts,
            "symbol":       symbol,
            "interval":     interval,
            "months":       months,
            "candle_ts":    candle_dt,
            "signal":       sig,
            "active":       json.dumps(active),
            "entry":        price,
            "p1h":          p1h,
            "p4h":          p4h,
            "p24h":         p24h,
            "pnl1h":        round((p1h  / price - 1) * 100, 3),
            "pnl4h":        round((p4h  / price - 1) * 100, 3),
            "pnl24h":       round((p24h / price - 1) * 100, 3),
        })

    return signals_found

def _store_hist_results(conn, rows: list):
    cur = conn.cursor()
    cur.executemany(adapt_query("""
        INSERT INTO historical_backtest
          (run_ts, symbol, interval, months, candle_ts, signal, active_signals,
           entry_price, price_1h, price_4h, price_24h,
           pnl_1h_pct, pnl_4h_pct, pnl_24h_pct)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """), [(r["run_ts"], r["symbol"], r["interval"], r["months"], r["candle_ts"],
           r["signal"], r["active"], r["entry"],
           r["p1h"], r["p4h"], r["p24h"],
           r["pnl1h"], r["pnl4h"], r["pnl24h"]) for r in rows])
    conn.commit()

def _summarise(rows: list, pnl_key: str) -> dict:
    vals = [r[pnl_key] for r in rows if r[pnl_key] is not None]
    if not vals:
        return {}
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    arr = np.array(vals)
    return {
        "count":          len(vals),
        "win_rate_pct":   round(len(wins) / len(vals) * 100, 1),
        "avg_pnl_pct":    round(float(np.mean(arr)), 3),
        "best_pct":       round(float(np.max(arr)), 3),
        "worst_pct":      round(float(np.min(arr)), 3),
        "profit_factor":  round(sum(wins) / (-sum(losses)), 3) if losses else 999.0,
    }

@app.get("/backtest/historical/{symbol}")
def historical_backtest(
    symbol: str,
    interval: str = "1h",
    months: int = 6,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY")
):
    """
    Haalt historische OHLCV-data op van Binance en draait alle 5 strategieën eroverheen.
    months=3/6/12/24 → terugkijken in maanden
    months=0 → ALLES wat Binance heeft (MAX, voor BTC bijv. terug tot 2017)
    interval=1h (standaard) — kan ook 4h of 1d zijn voor meer bereik.
    """
    auth(x_api_key)
    try:
        symbol = symbol.upper()
        run_ts = datetime.now(timezone.utc).isoformat()

        # Data ophalen
        klines = _fetch_klines_paginated(symbol, interval, months)
        if len(klines) < 220:
            raise HTTPException(status_code=400,
                detail=f"Te weinig historische data: {len(klines)} candles gevonden.")

        # Signalen berekenen
        rows = _run_hist_signals(klines, symbol, interval, months, run_ts)

        # Opslaan in DB (verwijder eerdere run voor zelfde symbol+interval)
        conn = get_conn()
        _ensure_hist_table(conn)
        cur = conn.cursor()
        cur.execute(adapt_query("DELETE FROM historical_backtest WHERE symbol=? AND interval=? AND months=?"),
                     (symbol, interval, months))
        _store_hist_results(conn, rows)
        conn.close()

        # Samenvatting
        by_signal: dict = {}
        for r in rows:
            by_signal.setdefault(r["signal"], []).append(r)

        summary_by_signal = {}
        for sig, srows in by_signal.items():
            summary_by_signal[sig] = {
                "1h":  _summarise(srows, "pnl1h"),
                "4h":  _summarise(srows, "pnl4h"),
                "24h": _summarise(srows, "pnl24h"),
            }

        return {
            "symbol":          symbol,
            "interval":        interval,
            "months":          months,
            "candles":         len(klines),
            "signals_found":   len(rows),
            "by_signal":       summary_by_signal,
            "overall_1h":      _summarise(rows, "pnl1h"),
            "overall_4h":      _summarise(rows, "pnl4h"),
            "overall_24h":     _summarise(rows, "pnl24h"),
            "run_ts":          run_ts,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/backtest/historical/{symbol}/signals")
def historical_signals(
    symbol: str,
    interval: str = "1h",
    months: int = 6,
    limit: int = 100,
    signal_filter: str = "",
    x_api_key: str | None = Header(default=None, alias="X-API-KEY")
):
    """Haal de individuele signalen op van de meest recente historische backtest."""
    auth(x_api_key)
    conn = get_conn()
    _ensure_hist_table(conn)
    cur = conn.cursor()
    sym = symbol.upper()
    if signal_filter:
        cur.execute(adapt_query("""
            SELECT candle_ts, signal, active_signals, entry_price,
                   pnl_1h_pct, pnl_4h_pct, pnl_24h_pct
            FROM historical_backtest
            WHERE symbol=? AND interval=? AND months=? AND signal=?
            ORDER BY candle_ts DESC LIMIT ?
        """), (sym, interval, months, signal_filter.upper(), limit))
    else:
        cur.execute(adapt_query("""
            SELECT candle_ts, signal, active_signals, entry_price,
                   pnl_1h_pct, pnl_4h_pct, pnl_24h_pct
            FROM historical_backtest
            WHERE symbol=? AND interval=? AND months=?
            ORDER BY candle_ts DESC LIMIT ?
        """), (sym, interval, months, limit))
    rows = cur.fetchall()
    conn.close()
    return [{"ts": r[0], "signal": r[1], "active": json.loads(r[2] or "[]"),
             "entry": r[3], "pnl_1h": r[4], "pnl_4h": r[5], "pnl_24h": r[6]}
            for r in rows]


@app.get("/balance")
def get_balance(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Toon demo account balans overzicht — echte virtuele $1000 tracking."""
    auth(x_api_key)
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Demo balance tabel (aanmaken als hij nog niet bestaat)
        cur.execute(adapt_query("""CREATE TABLE IF NOT EXISTS demo_balance(
            id INTEGER PRIMARY KEY CHECK (id = 1),
            balance REAL NOT NULL DEFAULT 1000.0,
            peak_balance REAL NOT NULL DEFAULT 1000.0,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            total_volume_usdt REAL DEFAULT 0
        )"""))
        cur.execute(adapt_query("INSERT OR IGNORE INTO demo_balance(id, balance, peak_balance) VALUES (1, 1000.0, 1000.0)"))
        conn.commit()

        cur.execute("SELECT balance, peak_balance, total_trades, winning_trades, total_volume_usdt FROM demo_balance WHERE id=1")
        row = cur.fetchone()
        balance, peak, total, wins, vol = (row[0], row[1], row[2], row[3], row[4]) if row else (1000.0, 1000.0, 0, 0, 0)

        # Signal performance stats
        cur.execute("""
            SELECT COUNT(*), AVG(pnl_1h_pct),
                   AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100
            FROM signal_performance WHERE status='closed'
        """)
        sp = cur.fetchone()

        # Recente demo trades
        cur.execute(adapt_query("""CREATE TABLE IF NOT EXISTS demo_account(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, symbol TEXT, action TEXT, price REAL,
            virtual_size_usdt REAL, virtual_pnl_usdt REAL DEFAULT 0,
            balance_after REAL, signal TEXT, note TEXT
        )"""))
        cur.execute("""
            SELECT ts, symbol, action, price, virtual_size_usdt, virtual_pnl_usdt, signal
            FROM demo_account ORDER BY id DESC LIMIT 10
        """)
        recent = [{
            "ts": r[0], "symbol": r[1], "side": r[2],
            "price": r[3], "size": round((r[4] or 0) / r[3], 6) if r[3] else 0,
            "pnl_usdt": r[5], "signal": r[6]
        } for r in cur.fetchall()]
        conn.close()

        win_rate = round(wins / total * 100, 1) if total > 0 else round((sp[2] or 0), 1)
        pnl_total = round(balance - 1000.0, 2)
        return {
            "account_type":      "demo",
            "exchange":          "BloFin Demo",
            "demo_start_usdt":   1000.0,
            "balance":           round(balance, 2),
            "peak_balance":      round(peak, 2),
            "pnl_total_usdt":    pnl_total,
            "pnl_total_pct":     round(pnl_total / 10, 2),
            "total_orders":      total or (sp[0] or 0),
            "winning_trades":    wins,
            "win_rate_pct":      win_rate,
            "total_volume_usdt": round(vol, 2),
            "signals_evaluated": sp[0] or 0,
            "avg_pnl_1h_pct":    round(sp[1] or 0, 3),
            "recent_orders":     recent,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Trading halt state ────────────────────────────────────────────────────
# Opgeslagen in geheugen + state file voor apex_engine

HALT_FILE = "/var/apex/trading_halt.json"

_trading_halt: dict = {"halted": False, "paused_until": None, "reason": ""}
_pending_answers: dict = {}   # q_id → antwoord

# ClawBot model instelling (in-memory, geset via Telegram /clawbot commando)
_clawbot_model: str = "claude-haiku-4-5-20251001"   # standaard = Haiku (goedkoop)

# Goedgekeurde nieuwe coins (buiten de vaste whitelist)
# Persistent in JSON bestand, beheerd via Telegram /coingoedkeuren
APPROVED_COINS_FILE = "/var/apex/approved_coins.json"

def _load_approved_coins() -> dict:
    try:
        with open(APPROVED_COINS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"approved": [], "pending": [], "rejected": []}
    except Exception:
        return {"approved": [], "pending": [], "rejected": []}

def _save_approved_coins(data: dict):
    try:
        with open(APPROVED_COINS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

_approved_coins = _load_approved_coins()


def _write_halt_file():
    try:
        with open(HALT_FILE, "w") as f:
            json.dump(_trading_halt, f)
    except Exception:
        pass


class TradingPauseRequest(BaseModel):
    minutes: int = 30
    reason: str = ""

class TradingAnswerRequest(BaseModel):
    q_id: str
    antwoord: str   # "ok" | "stop" | "skip"


@app.post("/trading/halt")
def trading_halt(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Noodstop — staak alle orders onmiddellijk."""
    auth(x_api_key)
    _trading_halt["halted"] = True
    _trading_halt["paused_until"] = None
    _trading_halt["reason"] = "manual noodstop"
    _write_halt_file()
    return {"status": "halted", "message": "Trading gestopt."}


@app.post("/trading/resume")
def trading_resume(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Hervat trading na noodstop of pauze."""
    auth(x_api_key)
    _trading_halt["halted"] = False
    _trading_halt["paused_until"] = None
    _trading_halt["reason"] = ""
    _write_halt_file()
    return {"status": "resumed", "message": "Trading hervat."}


@app.post("/trading/pause")
def trading_pause(
    body: TradingPauseRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Pauzeert trading voor X minuten."""
    auth(x_api_key)
    until = datetime.now(timezone.utc) + timedelta(minutes=body.minutes)
    _trading_halt["halted"] = False
    _trading_halt["paused_until"] = until.isoformat()
    _trading_halt["reason"] = body.reason or f"pauze {body.minutes} minuten"
    _write_halt_file()
    return {"status": "paused", "paused_until": until.isoformat(), "minutes": body.minutes}


@app.get("/trading/status")
def trading_status(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Geeft huidige trading halt/pauze status."""
    auth(x_api_key)
    return _trading_halt.copy()


@app.post("/trading/answer")
def trading_answer(
    body: TradingAnswerRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Sla gebruikersantwoord op voor ask_user_with_countdown."""
    auth(x_api_key)
    _pending_answers[body.q_id] = body.antwoord
    return {"q_id": body.q_id, "antwoord": body.antwoord}


@app.get("/trading/answer")
def get_trading_answer(
    q_id: str = Query(default=""),
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Poll voor antwoord op een specifieke vraag (q_id). Verwijdert het na lezen."""
    auth(x_api_key)
    antwoord = _pending_answers.pop(q_id, None)
    return {"q_id": q_id, "antwoord": antwoord}


# ── Exchange prijzen proxy (CORS-safe voor dashboard) ─────────────────────
BLOFIN_API_KEY        = os.getenv("BLOFIN_API_KEY", "")
BLOFIN_API_SECRET     = os.getenv("BLOFIN_API_SECRET", "")
BLOFIN_API_PASSPHRASE = os.getenv("BLOFIN_API_PASSPHRASE", "")

_EXCH_FETCHERS = {}  # lazy cache

def _fetch_binance_spot(sym: str):
    r = requests.get("https://api.binance.com/api/v3/ticker/price",
                     params={"symbol": sym}, timeout=5)
    return float(r.json()["price"])

def _fetch_bybit_spot(sym: str):
    bsym = sym.replace("USDT", "") + "-USDT"
    r = requests.get("https://api.bybit.com/v5/market/tickers",
                     params={"category": "spot", "symbol": bsym}, timeout=5)
    items = r.json()["result"]["list"]
    return float(items[0]["lastPrice"])

def _fetch_coinbase_spot(sym: str):
    base = sym.replace("USDT", "")
    r = requests.get(f"https://api.coinbase.com/v2/prices/{base}-USD/spot", timeout=5)
    return float(r.json()["data"]["amount"])

def _fetch_okx_spot(sym: str):
    osym = sym.replace("USDT", "") + "-USDT"
    r = requests.get("https://www.okx.com/api/v5/market/ticker",
                     params={"instId": osym}, timeout=5)
    return float(r.json()["data"][0]["last"])

def _fetch_kraken_spot(sym: str):
    base = sym.replace("USDT", "")
    kbase = "XBT" if base == "BTC" else base
    r = requests.get("https://api.kraken.com/0/public/Ticker",
                     params={"pair": f"{kbase}USDT"}, timeout=5)
    result = r.json()["result"]
    key = list(result.keys())[0]
    return float(result[key]["c"][0])

def _fetch_blofin_spot(sym: str):
    bsym = sym.replace("USDT", "") + "-USDT"
    r = requests.get("https://openapi.blofin.com/api/v1/market/tickers",
                     params={"instId": bsym}, timeout=5)
    data = r.json().get("data", [])
    if not data:
        raise ValueError("Geen data van BloFin")
    return float(data[0]["last"])

_SPOT_FETCHERS = {
    "binance":  _fetch_binance_spot,
    "bybit":    _fetch_bybit_spot,
    "coinbase": _fetch_coinbase_spot,
    "okx":      _fetch_okx_spot,
    "kraken":   _fetch_kraken_spot,
    "blofin":   _fetch_blofin_spot,
}

@app.get("/market/prices/{symbol}")
def market_prices(symbol: str,
                  x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """
    Haalt spotprijzen op van alle exchanges (Binance, Bybit, Coinbase, OKX, Kraken, BloFin).
    Proxied via backend zodat browser geen CORS-problemen heeft.
    """
    auth(x_api_key)
    sym = symbol.upper()
    prices = {}
    for name, fetcher in _SPOT_FETCHERS.items():
        try:
            prices[name] = round(fetcher(sym), 8)
        except Exception as e:
            prices[name] = None

    # Gewogen consensus (zelfde als exchange_intel.py)
    weights = {"coinbase": 0.35, "binance": 0.25, "bybit": 0.20, "okx": 0.12, "kraken": 0.08}
    w_sum, w_total = 0.0, 0.0
    for ex, w in weights.items():
        if prices.get(ex) is not None:
            w_sum += prices[ex] * w
            w_total += w
    consensus = round(w_sum / w_total, 6) if w_total > 0 else None

    return {
        "symbol":    sym,
        "prices":    prices,
        "consensus": consensus,
        "ts":        datetime.now(timezone.utc).isoformat(),
    }


@app.get("/clawbot/model")
def clawbot_get_model(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Haal huidige ClawBot model instelling op."""
    auth(x_api_key)
    return {
        "model": _clawbot_model,
        "is_premium": _clawbot_model != "claude-haiku-4-5-20251001",
        "beschikbare_modellen": {
            "haiku":  "claude-haiku-4-5-20251001  (standaard — goedkoop)",
            "sonnet": "claude-sonnet-4-6           (premium — alleen bij problemen)",
        }
    }


class ClawbotModelRequest(BaseModel):
    model: str   # "haiku" of "sonnet"


@app.post("/clawbot/model")
def clawbot_set_model(
    body: ClawbotModelRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Stel ClawBot model in. Alleen haiku of sonnet toegestaan."""
    auth(x_api_key)
    global _clawbot_model
    model_map = {
        "haiku":  "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
    }
    if body.model.lower() not in model_map:
        raise HTTPException(status_code=400, detail="Gebruik 'haiku' of 'sonnet'")
    _clawbot_model = model_map[body.model.lower()]
    return {"model": _clawbot_model, "status": "ingesteld"}


class CoinApproveRequest(BaseModel):
    symbol: str
    action: str   # "approve" | "reject" | "pending"


@app.get("/coins/approved")
def coins_get_approved(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Haal alle goedgekeurde, wachtende en afgewezen nieuwe coins op."""
    auth(x_api_key)
    global _approved_coins
    _approved_coins = _load_approved_coins()   # altijd vers laden
    return _approved_coins


@app.post("/coins/approved")
def coins_set_approved(
    body: CoinApproveRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Keur een coin goed, wijs hem af of zet hem terug op wachtend."""
    auth(x_api_key)
    global _approved_coins
    sym = body.symbol.upper()
    action = body.action.lower()
    if action not in ("approve", "reject", "pending"):
        raise HTTPException(status_code=400, detail="Gebruik 'approve', 'reject' of 'pending'")

    # Verwijder uit alle lijsten
    for key in ("approved", "rejected", "pending"):
        if sym in _approved_coins.get(key, []):
            _approved_coins[key].remove(sym)

    if action == "approve":
        if sym not in _approved_coins["approved"]:
            _approved_coins["approved"].append(sym)
    elif action == "reject":
        if sym not in _approved_coins["rejected"]:
            _approved_coins["rejected"].append(sym)
    else:
        if sym not in _approved_coins["pending"]:
            _approved_coins["pending"].append(sym)

    _save_approved_coins(_approved_coins)
    return {"ok": True, "symbol": sym, "action": action, "coins": _approved_coins}


@app.post("/coins/pending")
def coins_add_pending(
    body: CoinApproveRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Voeg een nieuwe coin toe als wachtend (gestuurd door apex_engine als Kimi hem selecteert)."""
    auth(x_api_key)
    global _approved_coins
    sym = body.symbol.upper()
    # Niet toevoegen als al goedgekeurd of afgewezen
    if sym in _approved_coins.get("approved", []):
        return {"ok": True, "symbol": sym, "status": "already_approved"}
    if sym in _approved_coins.get("rejected", []):
        return {"ok": True, "symbol": sym, "status": "rejected"}
    if sym not in _approved_coins.get("pending", []):
        _approved_coins["pending"].append(sym)
        _save_approved_coins(_approved_coins)
    return {"ok": True, "symbol": sym, "status": "pending"}


@app.get("/history/prices/{symbol}")
def history_prices(symbol: str, hours: int = 24,
                   x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Historische prijs snapshots voor een coin."""
    auth(x_api_key)
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(adapt_query(
            """SELECT ts, price, rsi, signal, change_pct, tf_bias, volume_usdt
               FROM price_snapshots
               WHERE symbol=? AND ts >= datetime('now', ?)
               ORDER BY ts ASC LIMIT 500"""),
            (symbol.upper(), f"-{hours} hours")
        )
        rows = cur.fetchall()
        conn.close()
        return {"symbol": symbol.upper(), "hours": hours, "data": [
            {"ts": r[0], "price": r[1], "rsi": r[2], "signal": r[3],
             "change_pct": r[4], "tf_bias": r[5], "volume_usdt": r[6]}
            for r in rows
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/crash/{symbol}")
def history_crash(symbol: str, hours: int = 48,
                  x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Historische pre-crash scores voor een coin."""
    auth(x_api_key)
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(adapt_query(
            """SELECT ts, score FROM crash_score_log
               WHERE symbol=? AND ts >= datetime('now', ?)
               ORDER BY ts ASC LIMIT 1000"""),
            (symbol.upper(), f"-{hours} hours")
        )
        rows = cur.fetchall()
        conn.close()
        return {"symbol": symbol.upper(), "hours": hours,
                "data": [{"ts": r[0], "score": r[1]} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/events")
def history_events(hours: int = 72, event_type: str = "", symbol: str = "",
                   x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Recente marktgebeurtenissen (BTC cascade, flash crash, pre-crash, enz.)."""
    auth(x_api_key)
    try:
        conn = get_conn()
        cur = conn.cursor()
        query = ("SELECT ts, event_type, symbol, severity, value, description "
                 "FROM market_events WHERE ts >= datetime('now', ?)")
        params = [f"-{hours} hours"]
        if event_type:
            query += " AND event_type=?"; params.append(event_type.upper())
        if symbol:
            query += " AND symbol=?"; params.append(symbol.upper())
        query += " ORDER BY ts DESC LIMIT 200"
        cur.execute(adapt_query(query), params)
        rows = cur.fetchall()
        conn.close()
        return {"hours": hours, "events": [
            {"ts": r[0], "type": r[1], "symbol": r[2],
             "severity": r[3], "value": r[4], "description": r[5]}
            for r in rows
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/summary/{symbol}")
def history_summary(symbol: str,
                    x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """AI-context samenvatting: prijs range 24u, crash scores, recente events, signaal stats."""
    auth(x_api_key)
    try:
        sym = symbol.upper()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(adapt_query(
            """SELECT AVG(price), MIN(price), MAX(price), COUNT(*),
                      AVG(rsi), MAX(rsi), MIN(rsi)
               FROM price_snapshots WHERE symbol=?
               AND ts >= datetime('now', '-24 hours')"""), (sym,))
        p = cur.fetchone()
        cur.execute(adapt_query(
            "SELECT MAX(score), AVG(score) FROM crash_score_log WHERE symbol=? "
            "AND ts >= datetime('now', '-24 hours')"), (sym,))
        c = cur.fetchone()
        cur.execute(adapt_query(
            """SELECT event_type, severity, description, ts FROM market_events
               WHERE (symbol=? OR symbol IS NULL) AND ts >= datetime('now', '-48 hours')
               ORDER BY ts DESC LIMIT 15"""), (sym,))
        e = cur.fetchall()
        cur.execute(adapt_query(
            """SELECT signal, COUNT(*), AVG(pnl_1h_pct)
               FROM signal_performance WHERE symbol=? AND status='closed'
               GROUP BY signal ORDER BY COUNT(*) DESC LIMIT 5"""), (sym,))
        sig = cur.fetchall()
        conn.close()
        return {
            "symbol": sym,
            "price_24h": {
                "avg": round(p[0] or 0, 6), "min": round(p[1] or 0, 6),
                "max": round(p[2] or 0, 6), "snapshots": p[3],
                "avg_rsi": round(p[4] or 0, 1), "max_rsi": p[5], "min_rsi": p[6],
            } if p and p[0] else {},
            "crash_24h": {
                "max_score": round(c[0] or 0, 1),
                "avg_score": round(c[1] or 0, 1),
            } if c and c[0] else {},
            "recent_events": [
                {"type": r[0], "severity": r[1], "desc": r[2], "ts": r[3]}
                for r in e
            ],
            "signal_stats": [
                {"signal": r[0], "count": r[1], "avg_pnl_1h": round(r[2] or 0, 3)}
                for r in sig
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── OpenClaw Agent Runtime Endpoints ────────────────────────────────────────

# Backtest job store (in-memory, eenvoudig genoeg)
_backtest_jobs: dict = {}   # job_id -> {status, result, ts}

class BacktestRunRequest(BaseModel):
    symbol: str
    interval: str = "1h"
    limit: int = 500
    agent: str = "openclaw_runtime"


@app.post("/backtest/run")
def backtest_run(
    body: BacktestRunRequest,
    background_tasks: BackgroundTasks,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Start een backtest job asynchroon. Geeft job_id terug."""
    auth(x_api_key)
    import uuid
    job_id = str(uuid.uuid4())[:8]
    _backtest_jobs[job_id] = {"status": "running", "result": None, "ts": datetime.now(timezone.utc).isoformat()}

    def _run(job_id: str, symbol: str, interval: str, limit: int):
        try:
            import talib
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
                timeout=15
            )
            r.raise_for_status()
            data = r.json()
            close  = np.array([float(c[4]) for c in data])
            high   = np.array([float(c[2]) for c in data])
            low    = np.array([float(c[3]) for c in data])
            rsi          = talib.RSI(close, 14)
            _, _, hist   = talib.MACD(close, 12, 26, 9)
            ema20        = talib.EMA(close, 20)
            ema50        = talib.EMA(close, 50)
            fee    = 6 / 10000
            trades = []
            pos    = None
            for i in range(50, len(close)):
                if any(np.isnan(x[i]) for x in [rsi, hist, ema20, ema50]):
                    continue
                price = close[i]
                if pos is None and rsi[i] < 45 and hist[i] > 0:
                    pos = price
                elif pos is not None and (rsi[i] > 60 or price < pos * 0.97):
                    pnl = (price / pos - 1) - 2 * fee
                    trades.append(round(pnl * 100, 4))
                    pos = None
            if not trades:
                _backtest_jobs[job_id] = {"status": "done", "result": {"symbol": symbol, "trades": 0}, "ts": datetime.now(timezone.utc).isoformat()}
                return
            wins   = [p for p in trades if p > 0]
            losses = [abs(p) for p in trades if p <= 0]
            arr    = np.array(trades)
            eq     = np.cumsum(arr)
            peak   = np.maximum.accumulate(eq)
            result = {
                "symbol": symbol, "interval": interval, "bars": len(close),
                "trades": len(trades),
                "win_rate": round(len(wins) / len(trades) * 100, 2),
                "profit_factor": round(sum(wins) / sum(losses), 3) if losses else 999.0,
                "max_drawdown_pct": round(float(np.max(peak - eq)), 4),
                "sharpe": round(float(np.mean(arr) / np.std(arr) * np.sqrt(len(arr))), 3) if np.std(arr) > 0 else 0.0,
                "total_return_pct": round(float(sum(trades)), 4),
            }
            _backtest_jobs[job_id] = {"status": "done", "result": result, "ts": datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            _backtest_jobs[job_id] = {"status": "error", "result": {"error": str(e)}, "ts": datetime.now(timezone.utc).isoformat()}

    background_tasks.add_task(_run, job_id, body.symbol.upper(), body.interval, body.limit)
    return {"job_id": job_id, "status": "running", "symbol": body.symbol.upper()}


@app.get("/backtest/result/{job_id}")
def backtest_result(
    job_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Haal backtest resultaat op via job_id."""
    auth(x_api_key)
    job = _backtest_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job niet gevonden")
    return {"job_id": job_id, **job}


@app.get("/metrics/performance")
def metrics_performance(
    limit: int = 100,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Geaggregeerde strategie-performance voor OpenClaw agents."""
    auth(x_api_key)
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Per signaaltype: win rate, gem. PnL 1u en 4u
        cur.execute(adapt_query("""
            SELECT signal,
                   COUNT(*) as n,
                   ROUND(AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
                   ROUND(AVG(pnl_1h_pct), 3) as avg_pnl_1h,
                   ROUND(AVG(pnl_4h_pct), 3) as avg_pnl_4h,
                   ROUND(MIN(pnl_1h_pct), 3) as worst_1h,
                   ROUND(MAX(pnl_1h_pct), 3) as best_1h
            FROM signal_performance
            WHERE pnl_1h_pct IS NOT NULL
            GROUP BY signal ORDER BY n DESC LIMIT 10
        """))
        sig_rows = cur.fetchall()
        # Per coin: win rate
        cur.execute(adapt_query("""
            SELECT symbol,
                   COUNT(*) as n,
                   ROUND(AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
                   ROUND(AVG(pnl_1h_pct), 3) as avg_pnl_1h
            FROM signal_performance
            WHERE pnl_1h_pct IS NOT NULL
            GROUP BY symbol ORDER BY n DESC LIMIT 10
        """))
        coin_rows = cur.fetchall()
        # Overall
        cur.execute(adapt_query("""
            SELECT COUNT(*) as total,
                   ROUND(AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
                   ROUND(AVG(pnl_1h_pct), 3) as avg_pnl_1h,
                   ROUND(SUM(pnl_1h_pct), 3) as total_pnl_1h
            FROM signal_performance WHERE pnl_1h_pct IS NOT NULL
        """))
        overall = cur.fetchone()
        # Pre-crash statistieken
        cur.execute(adapt_query("""
            SELECT ROUND(AVG(score), 1) as avg_score, ROUND(MAX(score), 1) as max_score,
                   COUNT(*) as readings
            FROM crash_score_log WHERE ts >= datetime('now', '-24 hours')
        """))
        crash_stats = cur.fetchone()
        conn.close()
        return {
            "overall": {
                "total_signals": overall[0] or 0,
                "win_rate_pct": overall[1] or 0,
                "avg_pnl_1h_pct": overall[2] or 0,
                "total_pnl_1h_pct": overall[3] or 0,
            },
            "by_signal": [
                {"signal": r[0], "n": r[1], "win_rate": r[2],
                 "avg_pnl_1h": r[3], "avg_pnl_4h": r[4], "worst_1h": r[5], "best_1h": r[6]}
                for r in sig_rows
            ],
            "by_coin": [
                {"symbol": r[0], "n": r[1], "win_rate": r[2], "avg_pnl_1h": r[3]}
                for r in coin_rows
            ],
            "crash_24h": {
                "avg_score": crash_stats[0] or 0,
                "max_score": crash_stats[1] or 0,
                "readings": crash_stats[2] or 0,
            },
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ConfirmPolicyRequest(BaseModel):
    confirm_required: bool


# Confirm policy (default: true — apply vereist Telegram goedkeuring)
_CONFIRM_REQUIRED: bool = os.getenv("CONFIRM_REQUIRED", "true").lower() == "true"


@app.get("/policy/confirm")
def get_confirm_policy(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Geeft huidige confirm policy terug."""
    auth(x_api_key)
    return {"confirm_required": _CONFIRM_REQUIRED}


@app.post("/policy/confirm")
def set_confirm_policy(
    body: ConfirmPolicyRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Stel confirm policy in (true = Telegram goedkeuring vereist voor apply)."""
    auth(x_api_key)
    global _CONFIRM_REQUIRED
    _CONFIRM_REQUIRED = body.confirm_required
    return {"confirm_required": _CONFIRM_REQUIRED, "status": "ingesteld"}


@app.get("/stream")
async def sse_stream(token: str = Query(default="")):
    """
    Server-Sent Events endpoint — stuurt bot state elke 2 seconden.
    Auth via ?token= query parameter (EventSource ondersteunt geen headers).
    Alleen sturen als timestamp veranderd is.
    """
    # Auth check
    if token != TOKEN:
        conn = get_conn()
        ensure_auth_tables(conn)
        cur = conn.cursor()
        cur.execute(adapt_query("SELECT expires_at FROM sessions WHERE token=?"), (token,))
        row = cur.fetchone()
        conn.close()
        if not row or (row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(row[0])) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Unauthorized")

    async def event_generator():
        last_ts = None
        while True:
            try:
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                ts = state.get("ts")
                if ts != last_ts:
                    last_ts = ts
                    yield {"event": "state", "data": json.dumps(state)}
            except FileNotFoundError:
                yield {"event": "state", "data": "{}"}
            except Exception as e:
                yield {"event": "error", "data": str(e)}
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — Log access voor Jojo1
# ══════════════════════════════════════════════════════════════════════════════

LOG_PATHS = {
    "control_api": LOG_PATH,
    "apex_engine": "/var/apex/apex_engine.log",
}


@app.get("/admin/logs")
def admin_logs(
    service: str = Query("control_api"),
    lines: int = Query(50),
    level: str = Query(""),
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    auth(x_api_key)
    lines = min(lines, 500)
    path = LOG_PATHS.get(service)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Log '{service}' niet gevonden. Beschikbaar: {list(LOG_PATHS.keys())}")
    with open(path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()
    if level:
        all_lines = [l for l in all_lines if level.upper() in l.upper()]
    result = [l.rstrip() for l in all_lines[-lines:]]
    return {"service": service, "lines": result, "total": len(result)}


# ══════════════════════════════════════════════════════════════════════════════
# GATEKEEPER API — Structured proposal system for OpenClaw Operator
# ══════════════════════════════════════════════════════════════════════════════

# ── Policy constants (hardcoded) ──────────────────────────────────────────────
PARAM_BOUNDS = {
    "rsi_buy_threshold":  (20, 40),
    "rsi_chop_max":       (45, 65),
    "rsi_sell_threshold": (60, 80),
    "stoploss_pct":       (1.5, 6.0),
    "takeprofit_pct":     (3.0, 12.0),
    "position_size_base": (1, 5),
    "max_positions":      (1, 6),
}
MAX_APPLIES_PER_DAY = 3
FLASHCRASH_AUTO_ACTIONS = {"PAUSE", "NO_BUY", "EXIT_ONLY"}
PROPOSAL_TYPES = {"PAUSE", "RESUME", "PARAM_CHANGE", "COIN_ALLOW", "RUN_BACKTEST", "DEPLOY_STAGING"}

_applies_today: dict = {"date": "", "count": 0}
_macro_context: dict = {}
_confirm_tokens: dict = {}  # {proposal_id: otp_code}


def _ensure_proposals_v2(conn):
    """Ensure proposals table has the v2 columns."""
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS proposals_v2(
        id TEXT PRIMARY KEY,
        ts TEXT NOT NULL,
        type TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        reason TEXT NOT NULL DEFAULT '',
        requested_by TEXT NOT NULL DEFAULT 'unknown',
        requires_confirm INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'pending',
        confirmed_at TEXT,
        applied_at TEXT
    )""")
    conn.commit()


def _check_applies_limit():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _applies_today["date"] != today:
        _applies_today["date"] = today
        _applies_today["count"] = 0
    if _applies_today["count"] >= MAX_APPLIES_PER_DAY:
        raise HTTPException(status_code=429, detail=f"Max {MAX_APPLIES_PER_DAY} applies per dag bereikt")


def _validate_param_bounds(payload: dict) -> list:
    """Validate and clamp params. Returns list of violations."""
    violations = []
    for key, (lo, hi) in PARAM_BOUNDS.items():
        if key in payload:
            val = payload[key]
            if not isinstance(val, (int, float)):
                violations.append(f"{key}: niet numeriek ({val})")
                continue
            if val < lo or val > hi:
                violations.append(f"{key}: {val} buiten grenzen [{lo}, {hi}]")
                payload[key] = max(lo, min(hi, val))  # clamp
    return violations


def _send_confirm_telegram(proposal_id: str, ptype: str, reason: str, otp: str):
    """Stuur confirm verzoek naar Telegram."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log.warning(f"OTP niet verzonden voor {proposal_id}: TG_BOT_TOKEN of TG_CHAT_ID niet geconfigureerd")
        return
    log.info(f"OTP verzenden voor proposal {proposal_id} naar chat {TG_CHAT_ID}")
    # HTML parse mode is robuuster dan Markdown (geen problemen met underscores/asterisks)
    text = (
        f"🔐 <b>VOORSTEL {proposal_id}</b>\n"
        f"Type: <code>{ptype}</code>\n"
        f"Reden: {reason}\n\n"
        f"Bevestig met OTP: <code>{otp}</code>\n"
        f"Of via API: <code>POST /proposals/{proposal_id}/confirm</code> met OTP header"
    )
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not r.ok:
            # Fallback: stuur zonder formatting
            requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": f"VOORSTEL {proposal_id}\nType: {ptype}\nOTP: {otp}"},
                timeout=10,
            )
    except Exception:
        pass


# ── GET /status ───────────────────────────────────────────────────────────────
@app.get("/status")
def gatekeeper_status(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Volledige platform status voor OpenClaw Operator."""
    auth(x_api_key)

    # Trading state
    trading = _trading_halt.copy()

    # Bot state (latest signals)
    state = {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        pass

    # Risk flags
    risk_flags = []
    crash_max = state.get("crash_max_24h", 0)
    if crash_max and crash_max > 70:
        risk_flags.append(f"HIGH_CRASH_SCORE:{crash_max}")
    wr = state.get("overall_win_rate")
    if wr is not None and wr < 40:
        risk_flags.append(f"LOW_WIN_RATE:{wr:.0f}%")
    if trading.get("halted"):
        risk_flags.append("TRADING_HALTED")
    pu = trading.get("paused_until")
    if pu:
        risk_flags.append(f"PAUSED_UNTIL:{pu}")

    return {
        "mode": "demo",
        "allow_live": False,
        "trading": trading,
        "last_signals": state.get("coin_signals", {}),
        "open_positions": state.get("open_positions", []),
        "crash_max_24h": crash_max,
        "overall_win_rate": wr,
        "risk_flags": risk_flags,
        "macro_context": _macro_context,
        "applies_today": _applies_today["count"],
        "max_applies_per_day": MAX_APPLIES_PER_DAY,
    }


# ── POST /proposals ──────────────────────────────────────────────────────────
class ProposalV2(BaseModel):
    type: str
    payload: dict = {}
    reason: str = ""
    requested_by: str = "openclaw_operator"
    requires_confirm: bool = True


@app.post("/proposals")
def create_proposal(body: ProposalV2, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Dien een nieuw voorstel in via de Gatekeeper."""
    auth(x_api_key)

    if body.type not in PROPOSAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Ongeldig type: {body.type}. Toegestaan: {PROPOSAL_TYPES}")

    # Validate params for PARAM_CHANGE
    violations = []
    if body.type == "PARAM_CHANGE":
        violations = _validate_param_bounds(body.payload)

    # Flash-crash auto-actions don't require confirm
    auto_apply = body.type in FLASHCRASH_AUTO_ACTIONS and not body.requires_confirm

    proposal_id = secrets.token_hex(4)
    ts = datetime.now(timezone.utc).isoformat()
    otp = str(random.randint(100000, 999999))

    conn = get_conn()
    _ensure_proposals_v2(conn)
    cur = conn.cursor()
    cur.execute(adapt_query(
        "INSERT INTO proposals_v2(id, ts, type, payload_json, reason, requested_by, requires_confirm, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"),
        (proposal_id, ts, body.type, json.dumps(body.payload), body.reason,
         body.requested_by, 0 if auto_apply else 1,
         "auto_applied" if auto_apply else "pending"),
    )
    conn.commit()
    conn.close()

    result = {
        "ok": True,
        "proposal_id": proposal_id,
        "type": body.type,
        "status": "auto_applied" if auto_apply else "pending",
        "requires_confirm": not auto_apply,
    }

    if violations:
        result["param_violations"] = violations
        result["note"] = "Parameters zijn geclamped naar PARAM_BOUNDS"

    if auto_apply:
        # Execute flash-crash action immediately
        _execute_proposal(proposal_id, body.type, body.payload, body.reason)
        result["message"] = f"Flash-crash actie {body.type} automatisch uitgevoerd"
    else:
        # Store OTP and send to Telegram
        _confirm_tokens[proposal_id] = otp
        _send_confirm_telegram(proposal_id, body.type, body.reason, otp)
        result["message"] = "Wacht op Telegram bevestiging (OTP)"

    return result


# ── GET /proposals?state=pending ──────────────────────────────────────────────
@app.get("/proposals/v2")
def list_proposals_v2(
    state: str = Query(default="all"),
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Lijst voorstellen met optionele status filter."""
    auth(x_api_key)
    conn = get_conn()
    _ensure_proposals_v2(conn)
    cur = conn.cursor()
    if state == "all":
        cur.execute("SELECT * FROM proposals_v2 ORDER BY ts DESC LIMIT 100")
    else:
        cur.execute(adapt_query("SELECT * FROM proposals_v2 WHERE status=? ORDER BY ts DESC LIMIT 100"), (state,))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


# ── POST /proposals/{id}/confirm ──────────────────────────────────────────────
@app.post("/proposals/{proposal_id}/confirm")
def confirm_proposal(
    proposal_id: str,
    x_otp: str = Header(default="", alias="X-OTP"),
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Bevestig een voorstel met Telegram OTP."""
    auth(x_api_key)

    # Validate OTP
    expected_otp = _confirm_tokens.get(proposal_id)
    if not expected_otp:
        raise HTTPException(status_code=404, detail=f"Voorstel {proposal_id} niet gevonden of al bevestigd")
    if x_otp != expected_otp:
        raise HTTPException(status_code=403, detail="Ongeldig OTP")

    # Check daily limit
    _check_applies_limit()

    # Load proposal
    conn = get_conn()
    _ensure_proposals_v2(conn)
    cur = conn.cursor()
    cur.execute(adapt_query("SELECT type, payload_json, reason, status FROM proposals_v2 WHERE id=?"), (proposal_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Voorstel niet gevonden")
    ptype, payload_json, reason, status = row
    if status != "pending":
        conn.close()
        raise HTTPException(status_code=400, detail=f"Voorstel status is '{status}', niet 'pending'")

    payload = json.loads(payload_json)

    # Policy check for PARAM_CHANGE
    if ptype == "PARAM_CHANGE":
        violations = _validate_param_bounds(payload)
        if violations:
            conn.close()
            raise HTTPException(status_code=400, detail=f"PARAM_BOUNDS overtreding: {violations}")

    # ALLOW_LIVE mag NOOIT via proposal
    if payload.get("ALLOW_LIVE") or payload.get("allow_live"):
        conn.close()
        raise HTTPException(status_code=403, detail="ALLOW_LIVE mag NOOIT via proposal worden ingeschakeld")

    # Apply
    ts = datetime.now(timezone.utc).isoformat()
    cur.execute(adapt_query("UPDATE proposals_v2 SET status='confirmed', confirmed_at=?, applied_at=? WHERE id=?"),
                 (ts, ts, proposal_id))
    conn.commit()
    conn.close()

    _applies_today["count"] += 1
    del _confirm_tokens[proposal_id]

    _execute_proposal(proposal_id, ptype, payload, reason)

    return {
        "ok": True,
        "proposal_id": proposal_id,
        "status": "confirmed",
        "applied": True,
        "applies_today": _applies_today["count"],
    }


def _execute_proposal(proposal_id: str, ptype: str, payload: dict, reason: str):
    """Voer een goedgekeurd voorstel uit."""
    if ptype == "PAUSE":
        minutes = payload.get("minutes", 30)
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        _trading_halt["halted"] = False
        _trading_halt["paused_until"] = until.isoformat()
        _trading_halt["reason"] = reason or f"proposal {proposal_id}"
        _write_halt_file()
    elif ptype == "RESUME":
        _trading_halt["halted"] = False
        _trading_halt["paused_until"] = None
        _trading_halt["reason"] = ""
        _write_halt_file()
    elif ptype == "PARAM_CHANGE":
        # Write params to state file for apex_engine to pick up
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            state.setdefault("config_overrides", {}).update(payload)
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except Exception:
            pass
    # COIN_ALLOW, RUN_BACKTEST, DEPLOY_STAGING: logged but no direct execution


# ── POST /context/macro ───────────────────────────────────────────────────────
class MacroContextUpdate(BaseModel):
    analysis: dict = {}
    key_factors: list = []
    suggested_actions: list = []
    timestamp: str = ""


@app.post("/context/macro")
def update_macro_context(body: MacroContextUpdate, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Update macro-economische context (read-only store van Market Oracle)."""
    auth(x_api_key)
    _macro_context.update(body.dict())
    _macro_context["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"ok": True, "message": "Macro context bijgewerkt"}


@app.get("/context/macro")
def get_macro_context(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Haal huidige macro context op."""
    auth(x_api_key)
    return _macro_context


# ── GET /policy ───────────────────────────────────────────────────────────────
@app.get("/policy")
def get_policy(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Toon Gatekeeper policy regels."""
    auth(x_api_key)
    return {
        "param_bounds": {k: {"min": lo, "max": hi} for k, (lo, hi) in PARAM_BOUNDS.items()},
        "max_applies_per_day": MAX_APPLIES_PER_DAY,
        "flashcrash_auto_actions": list(FLASHCRASH_AUTO_ACTIONS),
        "allowed_proposal_types": list(PROPOSAL_TYPES),
        "allow_live": False,
        "confirm_required": True,
    }


# ── Setup Intelligence ─────────────────────────────────────────────────────────
_ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://jojo_analytics:8097")

# Drempels (zelfde als setup_judge.py)
_SJ_SKIP_WIN        = 25.0
_SJ_STERK_WIN       = 55.0
_SJ_SKIP_PNL        = -0.30
_SJ_STERK_PNL       = 0.20
_SJ_MIN_N           = 10
_SJ_MIN_N_STERK     = 20
_SJ_SCORE_STERK     = 70
_SJ_SCORE_TOESTAAN  = 50
_SJ_SCORE_ZWAK      = 30


def _sj_query(sql: str) -> list:
    try:
        r = requests.post(f"{_ANALYTICS_URL}/query", json={"sql": sql}, timeout=15)
        r.raise_for_status()
        return r.json().get("rows", [])
    except Exception as e:
        log.warning(f"setup/scan query fout: {e}")
        return []


def _sj_btc_regime() -> str:
    rows = _sj_query(
        "SELECT ema_bull FROM indicators_data "
        "WHERE symbol = 'BTCUSDT' AND interval = '1h' "
        "ORDER BY ts DESC LIMIT 1"
    )
    if not rows:
        return "onbekend"
    val = rows[0].get("ema_bull")
    if val is True or str(val).lower() in ("true", "1", "t"):
        return "bull"
    if val is False or str(val).lower() in ("false", "0", "f"):
        return "bear"
    return "onbekend"


def _sj_score(win, avg_1h, n, regime_boost=0):
    if win is None or avg_1h is None:
        return 0
    w, p = float(win), float(avg_1h)
    s = 0
    # Win rate (0-40)
    if w >= 55:   s += 40
    elif w >= 45: s += 30
    elif w >= 35: s += 20
    elif w >= 25: s += 10
    # PnL (0-30)
    if p >= 0.50:    s += 30
    elif p >= 0.20:  s += 25
    elif p >= 0.05:  s += 18
    elif p >= 0.00:  s += 12
    elif p >= -0.10: s += 6
    elif p >= -0.30: s += 2
    # N (0-15)
    if n >= 100:  s += 15
    elif n >= 50: s += 12
    elif n >= 20: s += 8
    elif n >= 10: s += 4
    # Regime boost
    s += max(0, min(15, int(regime_boost)))
    return max(0, min(100, s))


def _sj_edge_strength(win, avg_1h, n):
    if win is None or avg_1h is None or n < _SJ_MIN_N:
        return "geen"
    w, p = float(win), float(avg_1h)
    if w >= 55 and p >= 0.30 and n >= 30:
        return "sterk"
    if w >= 45 and p >= 0.10 and n >= 15:
        return "midden"
    if w >= 35 and p >= 0.0:
        return "zwak"
    return "negatief"


def _sj_process_row(row, current_regime: str) -> dict | None:
    n = int(row.get("n") or 0)
    if n < _SJ_MIN_N:
        return None

    def _f(k):  return round(float(row[k]), 3) if row.get(k) is not None else None
    def _f1(k): return round(float(row[k]), 1) if row.get(k) is not None else None

    win    = _f1("win1h")
    avg_1h = _f("avg_1h")
    avg_4h = _f("avg_4h")
    n_bull = int(row.get("n_bull") or 0)
    n_bear = int(row.get("n_bear") or 0)
    win_bull = _f1("win1h_bull")
    win_bear = _f1("win1h_bear")
    avg_bull = _f("avg_1h_bull")
    avg_bear = _f("avg_1h_bear")

    # Regime boost
    regime_boost = 0
    if current_regime in ("bull", "bear") and win is not None:
        win_r = win_bull if current_regime == "bull" else win_bear
        n_r   = n_bull   if current_regime == "bull" else n_bear
        if win_r is not None and n_r >= 5:
            delta = float(win_r) - float(win)
            regime_boost = max(0, min(15, int(delta / 2)))

    score = _sj_score(win, avg_1h, n, regime_boost)

    # Verdict
    if n < _SJ_MIN_N:
        verdict = "ONBEKEND"
    elif win is not None and win < _SJ_SKIP_WIN and avg_1h is not None and avg_1h < _SJ_SKIP_PNL:
        verdict = "SKIP"
    elif score >= _SJ_SCORE_STERK and win >= _SJ_STERK_WIN and avg_1h >= _SJ_STERK_PNL and n >= _SJ_MIN_N_STERK:
        verdict = "STERK"
    elif score >= _SJ_SCORE_TOESTAAN:
        verdict = "TOESTAAN"
    elif score >= _SJ_SCORE_ZWAK:
        verdict = "TOESTAAN_ZWAK"
    else:
        verdict = "SKIP"

    # Regime fit
    if current_regime in ("bull", "bear") and win is not None:
        win_r = win_bull if current_regime == "bull" else win_bear
        n_r   = n_bull   if current_regime == "bull" else n_bear
        if win_r is not None and n_r >= 5:
            delta = float(win_r) - float(win)
            regime_fit = f"{current_regime}_voordeel" if delta > 5 else (f"{current_regime}_nadeel" if delta < -5 else current_regime)
        else:
            regime_fit = "onvoldoende_data"
    else:
        regime_fit = "onbekend"

    # Bepaal hoeveel uur geleden het laatste signaal was
    last_ts_raw = row.get("last_signal_ts")
    last_signal_ts = None
    last_signal_hours_ago = None
    if last_ts_raw:
        try:
            if isinstance(last_ts_raw, datetime):
                ldt = last_ts_raw if last_ts_raw.tzinfo else last_ts_raw.replace(tzinfo=timezone.utc)
            else:
                ldt = datetime.fromisoformat(str(last_ts_raw).replace(" ", "T"))
                if ldt.tzinfo is None:
                    ldt = ldt.replace(tzinfo=timezone.utc)
            last_signal_ts = ldt.isoformat()
            last_signal_hours_ago = round((datetime.now(timezone.utc) - ldt).total_seconds() / 3600, 1)
        except Exception:
            pass

    return {
        "symbol":      row.get("symbol"),
        "signal":      row.get("signal"),
        "setup_score": score,
        "verdict":     verdict,
        "n":           n,
        "win_pct_1h":  win,
        "avg_1h":      avg_1h,
        "avg_4h":      avg_4h,
        "edge_strength": _sj_edge_strength(win, avg_1h, n),
        "regime_fit":  regime_fit,
        "n_bull":      n_bull,
        "n_bear":      n_bear,
        "win_bull":    win_bull,
        "win_bear":    win_bear,
        "avg_1h_bull": avg_bull,
        "avg_1h_bear": avg_bear,
        "last_signal_ts":         last_signal_ts,
        "last_signal_hours_ago":  last_signal_hours_ago,
    }


@app.get("/setup/scan")
def setup_scan(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """
    Bulk setup intelligence scan.
    Haalt stats op voor elke (symbol, signal) combinatie in historical_context.
    Berekent setup_score, verdict, regime_fit en edge_strength.
    """
    auth(x_api_key)

    # 1. Huidig BTC-regime
    btc_regime = _sj_btc_regime()

    # 2. Bulk query: alle coins × signalen in één call
    rows = _sj_query("""
        SELECT
            symbol,
            signal,
            COUNT(*) as n,
            AVG(pnl_1h_pct) as avg_1h,
            AVG(pnl_4h_pct) as avg_4h,
            100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0) as win1h,
            SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END) as n_bull,
            AVG(CASE WHEN btc_regime = 'bull' THEN pnl_1h_pct END) as avg_1h_bull,
            100.0 * SUM(CASE WHEN btc_regime = 'bull' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END), 0) as win1h_bull,
            SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END) as n_bear,
            AVG(CASE WHEN btc_regime = 'bear' THEN pnl_1h_pct END) as avg_1h_bear,
            100.0 * SUM(CASE WHEN btc_regime = 'bear' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END), 0) as win1h_bear,
            MAX(candle_ts) as last_signal_ts
        FROM historical_context
        WHERE pnl_1h_pct IS NOT NULL
          AND symbol != 'USDCUSDT'
        GROUP BY symbol, signal
        HAVING COUNT(*) >= 5
        ORDER BY symbol, signal
    """)

    # 3. Verwerk + score elke rij
    setups = []
    for row in rows:
        result = _sj_process_row(row, btc_regime)
        if result:
            setups.append(result)

    # 4. Sorteer op setup_score desc
    setups.sort(key=lambda x: x["setup_score"], reverse=True)

    # 5. Verdeling per verdict
    verdicts = {"STERK": 0, "TOESTAAN": 0, "TOESTAAN_ZWAK": 0, "SKIP": 0, "ONBEKEND": 0}
    for s in setups:
        verdicts[s["verdict"]] = verdicts.get(s["verdict"], 0) + 1

    return {
        "btc_regime":     btc_regime,
        "setups":         setups,
        "verdict_counts": verdicts,
        "total":          len(setups),
        "ts":             datetime.now(timezone.utc).isoformat(),
    }


def _detect_signal(row: dict) -> str | None:
    """Detecteert actief signaaltype op basis van actuele indicator waarden."""
    def _f(k): return float(row[k]) if row.get(k) is not None else None
    rsi       = _f("rsi")
    mh        = _f("macd_hist")
    adx       = _f("adx")
    sk        = _f("stoch_rsi_k")
    sd        = _f("stoch_rsi_d")
    vol_ratio = _f("volume_ratio")
    bb_pos    = str(row.get("bb_position") or "")
    ema_bull  = row.get("ema_bull") in (True, "true", "t", 1, "1", "True")

    if rsi is None: return None

    adx_strong  = adx is not None and adx > 25
    macd_bull   = mh is not None and mh > 0

    # BREAKOUT_BULL: prijs boven bovenste BB + RSI > 50 + hoog volume
    if bb_pos == "above_upper" and rsi > 50 and vol_ratio is not None and vol_ratio > 1.5:
        return "BREAKOUT_BULL"

    # MOMENTUM: golden cross + RSI groeizone + MACD bullish + ADX trending
    if ema_bull and 50 < rsi < 65 and macd_bull and adx_strong:
        return "MOMENTUM"

    # BUY via RSI-MACD: oversold + MACD draait omhoog
    if rsi < 32 and macd_bull:
        return "BUY"

    # BUY via StochRSI oversold
    if sk is not None and sd is not None and sk < 20 and sk > sd and rsi < 45:
        return "BUY"

    # BUY breed: oversold zone + niet dalend MACD
    if rsi < 35 and mh is not None and mh >= -50:
        return "BUY"

    return None


@app.get("/live/signals")
def live_signals(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """
    Actuele signalen per coin op basis van meest recente indicator waarden (1h).
    Detecteert actief signaaltype + P1 verdict + historische stats.
    """
    auth(x_api_key)

    # 1. Meest recente 1h indicators per coin
    ind_rows = _sj_query("""
        SELECT DISTINCT ON (symbol)
            symbol,
            EXTRACT(EPOCH FROM ts)::bigint as ts_unix,
            ts::text as ts_str,
            rsi, macd_hist, bb_width, bb_position,
            ema21, ema55, ema200, ema_bull,
            adx, stoch_rsi_k, stoch_rsi_d, volume_ratio, rsi_zone
        FROM indicators_data
        WHERE interval = '1h'
          AND symbol != 'USDCUSDT'
        ORDER BY symbol, ts DESC
    """)

    # 2. Aggregate P1 stats per (symbol, signal) — hergebruik setup/scan logica
    btc_regime = _sj_btc_regime()
    agg_rows = _sj_query("""
        SELECT
            symbol, signal,
            COUNT(*) as n,
            AVG(pnl_1h_pct) as avg_1h,
            AVG(pnl_4h_pct) as avg_4h,
            100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0) as win1h,
            SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END) as n_bull,
            AVG(CASE WHEN btc_regime = 'bull' THEN pnl_1h_pct END) as avg_1h_bull,
            100.0 * SUM(CASE WHEN btc_regime = 'bull' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END), 0) as win1h_bull,
            SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END) as n_bear,
            AVG(CASE WHEN btc_regime = 'bear' THEN pnl_1h_pct END) as avg_1h_bear,
            100.0 * SUM(CASE WHEN btc_regime = 'bear' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END), 0) as win1h_bear,
            MAX(candle_ts) as last_signal_ts
        FROM historical_context
        WHERE pnl_1h_pct IS NOT NULL AND symbol != 'USDCUSDT'
        GROUP BY symbol, signal HAVING COUNT(*) >= 5
    """)

    # Map (symbol, signal) → P1 info
    p1_map: dict = {}
    for row in agg_rows:
        row["symbol"] = row.get("symbol")
        result = _sj_process_row(row, btc_regime)
        if result:
            key = (result["symbol"], result["signal"])
            p1_map[key] = result

    # 3. Verwerk elke coin
    VERDICT_ORDER = {"STERK": 0, "TOESTAAN": 1, "TOESTAAN_ZWAK": 2, "SKIP": 3, "ONBEKEND": 4}
    signals = []
    for row in ind_rows:
        sym    = row.get("symbol")
        signal = _detect_signal(row)
        p1     = p1_map.get((sym, signal)) if signal else None

        def _f(k): return round(float(row[k]), 2) if row.get(k) is not None else None

        signals.append({
            "symbol":       sym,
            "ts_str":       row.get("ts_str"),
            "ts_unix":      row.get("ts_unix"),
            "rsi":          _f("rsi"),
            "rsi_zone":     row.get("rsi_zone"),
            "macd_hist":    _f("macd_hist"),
            "adx":          _f("adx"),
            "ema_bull":     row.get("ema_bull") in (True, "true", "t", 1, "1", "True"),
            "bb_position":  row.get("bb_position"),
            "volume_ratio": _f("volume_ratio"),
            "signal":       signal,
            "verdict":      p1["verdict"]      if p1 else None,
            "setup_score":  p1["setup_score"]  if p1 else None,
            "win_pct_1h":   p1["win_pct_1h"]   if p1 else None,
            "avg_1h":       p1["avg_1h"]        if p1 else None,
            "edge_strength": p1["edge_strength"] if p1 else None,
            "regime_fit":   p1["regime_fit"]    if p1 else None,
            "n":            p1["n"]             if p1 else None,
        })

    # Sorteer: actief signaal eerst, dan op verdict kwaliteit, dan op rsi laag→hoog
    signals.sort(key=lambda x: (
        0 if x["signal"] else 1,
        VERDICT_ORDER.get(x["verdict"] or "ONBEKEND", 4),
        x["rsi"] if x["rsi"] is not None else 99,
    ))

    n_active = sum(1 for s in signals if s["signal"])
    n_sterk  = sum(1 for s in signals if s["verdict"] == "STERK" and s["signal"])

    return {
        "signals":    signals,
        "btc_regime": btc_regime,
        "n_active":   n_active,
        "n_sterk":    n_sterk,
        "total":      len(signals),
        "ts":         datetime.now(timezone.utc).isoformat(),
    }


@app.get("/setup/chart-markers/{symbol}")
def setup_chart_markers(
    symbol: str,
    days: int = Query(default=180, ge=7, le=730),
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """
    Setup Intelligence markers per historische candle voor chart.html.
    Geeft STERK/TOESTAAN/TOESTAAN_ZWAK momenten terug vanuit historical_context,
    gescoord met dezelfde P1-logica als /setup/scan.
    """
    auth(x_api_key)
    sym = "".join(c for c in symbol if c.isalnum()).upper()

    # 1. Aggregate stats per signal type voor dit symbool (zelfde query als /setup/scan)
    btc_regime = _sj_btc_regime()
    agg_rows = _sj_query(f"""
        SELECT
            signal,
            COUNT(*) as n,
            AVG(pnl_1h_pct)  as avg_1h,
            AVG(pnl_4h_pct)  as avg_4h,
            100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0) as win1h,
            SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END) as n_bull,
            AVG(CASE WHEN btc_regime = 'bull' THEN pnl_1h_pct END) as avg_1h_bull,
            100.0 * SUM(CASE WHEN btc_regime = 'bull' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END), 0) as win1h_bull,
            SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END) as n_bear,
            AVG(CASE WHEN btc_regime = 'bear' THEN pnl_1h_pct END) as avg_1h_bear,
            100.0 * SUM(CASE WHEN btc_regime = 'bear' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END), 0) as win1h_bear
        FROM historical_context
        WHERE symbol = '{sym}'
          AND pnl_1h_pct IS NOT NULL
        GROUP BY signal
        HAVING COUNT(*) >= 5
    """)

    # Map signal → verdict + geaggregeerde stats
    signal_info: dict = {}
    for row in agg_rows:
        row["symbol"] = sym
        result = _sj_process_row(row, btc_regime)
        if result:
            signal_info[result["signal"]] = result

    # 2. Alleen signalen met STERK/TOESTAAN/TOESTAAN_ZWAK verdict (SKIP = ruis op grafiek)
    good_signals = [
        sig for sig, info in signal_info.items()
        if info["verdict"] in ("STERK", "TOESTAAN", "TOESTAAN_ZWAK")
    ]
    if not good_signals:
        return {
            "markers": [],
            "signal_verdicts": {s: i["verdict"] for s, i in signal_info.items()},
            "symbol": sym,
            "total": 0,
        }

    sig_list = ", ".join(f"'{s}'" for s in good_signals)
    hist_rows = _sj_query(f"""
        SELECT
            EXTRACT(EPOCH FROM candle_ts)::bigint as ts_unix,
            signal,
            pnl_1h_pct,
            pnl_4h_pct,
            rsi
        FROM historical_context
        WHERE symbol = '{sym}'
          AND signal IN ({sig_list})
          AND candle_ts >= NOW() - INTERVAL '{days} days'
        ORDER BY candle_ts ASC
        LIMIT 1000
    """)

    # 3. Bouw markers — koppel aggregate stats aan elke candle
    markers = []
    for row in hist_rows:
        sig  = row.get("signal")
        info = signal_info.get(sig, {})
        ts   = int(row.get("ts_unix") or 0)
        if not ts:
            continue
        markers.append({
            "time":        ts,
            "verdict":     info.get("verdict", "SKIP"),
            "signal":      sig,
            "pnl_1h":      row.get("pnl_1h_pct"),
            "pnl_4h":      row.get("pnl_4h_pct"),
            "rsi":         row.get("rsi"),
            "win_pct":     info.get("win_pct_1h"),
            "avg_1h_hist": info.get("avg_1h"),
            "n":           info.get("n"),
            "setup_score": info.get("setup_score"),
        })

    return {
        "markers":         markers,
        "signal_verdicts": {s: i["verdict"] for s, i in signal_info.items()},
        "symbol":          sym,
        "total":           len(markers),
    }


# ── Chart Data ─────────────────────────────────────────────────────────────────
def _ts_unix(ts_val) -> int:
    """Converteert timestamp string (met of zonder tz) naar Unix seconden (int)."""
    s = str(ts_val).strip().replace(" ", "T")
    # Verwijder timezone suffix — alles is UTC
    for sep in ("+", "Z"):
        idx = s.find(sep, 10)
        if idx != -1:
            s = s[:idx]
    try:
        return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


@app.get("/chart/markers/{symbol}")
def chart_markers(
    symbol:   str,
    interval: str = "1h",
    limit:    int = 300,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """
    Chart data voor één coin: OHLCV candles, EMA-lijnen, verdict-markers en crash-scores.
    interval: 1h | 4h  (voor 5m/15m haalt de browser Binance direct op)
    """
    auth(x_api_key)
    sym = "".join(c for c in symbol if c.isalnum())[:20].upper()
    iv  = interval if interval in ("1h", "4h") else "1h"

    # 1. OHLCV candles via jojo_analytics (PostgreSQL)
    raw_candles = _sj_query(f"""
        SELECT ts, open, high, low, close, volume
        FROM ohlcv_data
        WHERE symbol = '{sym}' AND interval = '{iv}'
        ORDER BY ts DESC
        LIMIT {min(limit, 1000)}
    """)
    candles = sorted([
        {
            "time":   _ts_unix(r["ts"]),
            "open":   float(r["open"]  or 0),
            "high":   float(r["high"]  or 0),
            "low":    float(r["low"]   or 0),
            "close":  float(r["close"] or 0),
            "volume": float(r["volume"] or 0),
        }
        for r in raw_candles
        if r.get("ts") and r.get("close")
    ], key=lambda x: x["time"])

    # 2. EMA-lijnen via jojo_analytics (alleen voor 1h)
    emas = []
    if iv == "1h":
        raw_emas = _sj_query(f"""
            SELECT ts, ema21, ema55, ema200
            FROM indicators_data
            WHERE symbol = '{sym}' AND interval = '1h'
            ORDER BY ts DESC
            LIMIT {min(limit, 1000)}
        """)
        emas = sorted([
            {
                "time":   _ts_unix(r["ts"]),
                "ema21":  float(r["ema21"])  if r.get("ema21")  is not None else None,
                "ema55":  float(r["ema55"])  if r.get("ema55")  is not None else None,
                "ema200": float(r["ema200"]) if r.get("ema200") is not None else None,
            }
            for r in raw_emas
            if r.get("ts") and r.get("ema21") is not None
        ], key=lambda x: x["time"])

    # 3. Verdicts rechtstreeks uit SQLite (verdict_log bestaat niet in PostgreSQL)
    verdicts = []
    try:
        import sqlite3 as _sqlite3
        _sc = _sqlite3.connect(DB_PATH)
        _cur = _sc.cursor()
        _cur.execute("""
            SELECT vl.ts, vl.verdict, vl.signal, vl.rsi_1h,
                   vl.avg_1h, vl.win_pct_1h, vl.n, vl.reden,
                   sp.entry_price, sp.pnl_1h_pct, sp.pnl_4h_pct
            FROM verdict_log vl
            LEFT JOIN signal_performance sp ON sp.id = vl.signal_perf_id
            WHERE vl.symbol = ?
            ORDER BY vl.ts ASC
        """, (sym,))
        for r in _cur.fetchall():
            t = _ts_unix(r[0])
            if t:
                verdicts.append({
                    "time":        t,
                    "verdict":     r[1],
                    "signal":      r[2],
                    "rsi":         round(float(r[3]), 1) if r[3] is not None else None,
                    "avg_1h_hist": round(float(r[4]), 3) if r[4] is not None else None,
                    "win_pct":     round(float(r[5]), 1) if r[5] is not None else None,
                    "n":           r[6],
                    "reden":       r[7],
                    "entry_price": float(r[8]) if r[8] is not None else None,
                    "pnl_1h":      round(float(r[9]),  3) if r[9]  is not None else None,
                    "pnl_4h":      round(float(r[10]), 3) if r[10] is not None else None,
                })
        _sc.close()
    except Exception as e:
        log.warning(f"chart_markers verdicts fout: {e}")

    # 4. Crash scores uit SQLite crash_score_log
    crash_scores = []
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(adapt_query("""
            SELECT ts, score FROM crash_score_log
            WHERE symbol = ?
            ORDER BY ts ASC
        """), (sym,))
        for r in cur.fetchall():
            t = _ts_unix(r[0])
            if t:
                crash_scores.append({"time": t, "score": round(float(r[1] or 0), 1)})
        conn.close()
    except Exception as e:
        log.warning(f"chart_markers crash_scores fout: {e}")

    return {
        "symbol":       sym,
        "interval":     iv,
        "candles":      candles,
        "emas":         emas,
        "verdicts":     verdicts,
        "crash_scores": crash_scores,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TestBot endpoints
# ══════════════════════════════════════════════════════════════════════════════

class TestBotOpen(BaseModel):
    symbol: str
    signal: str = ""
    setup_score: int = 0


@app.get("/testbot/status")
def testbot_status(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    return _tb.bot_status()


@app.post("/testbot/start")
def testbot_start(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    return _tb.start_bot()


@app.post("/testbot/stop")
def testbot_stop(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    return _tb.stop_bot()


@app.post("/testbot/open")
def testbot_open(body: TestBotOpen, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Handmatig een STERK trade openen (voor tests)."""
    auth(x_api_key)
    sym = "".join(c for c in body.symbol if c.isalnum()).upper()
    return _tb.manual_open(sym, body.signal, body.setup_score)


@app.get("/testbot/positions")
def testbot_positions(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Open posities met live Binance prijs en actuele PnL."""
    auth(x_api_key)
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("""
        SELECT id, symbol, signal, setup_score, entry_price,
               entry_ts, stake_usd, tp_pct, sl_pct, tp_price, sl_price
        FROM testbot_trades
        WHERE status = 'open'
        ORDER BY entry_ts ASC
    """))
    rows = cur.fetchall()
    conn.close()

    positions = []
    for r in rows:
        tid, sym, sig, score, ep, ets, stake, tp_pct, sl_pct, tp_p, sl_p = r
        ep = float(ep)

        # Live prijs
        live = _tb._binance_price(sym)
        if isinstance(ets, datetime):
            ets_dt = ets if ets.tzinfo else ets.replace(tzinfo=timezone.utc)
        else:
            try:
                ets_dt = datetime.fromisoformat(str(ets).replace(" ", "T"))
                if ets_dt.tzinfo is None:
                    ets_dt = ets_dt.replace(tzinfo=timezone.utc)
            except Exception:
                ets_dt = datetime.now(timezone.utc)

        age_s  = (datetime.now(timezone.utc) - ets_dt).total_seconds()
        pnl_pct = ((live - ep) / ep * 100) if live else None
        pnl_usd = (pnl_pct / 100 * float(stake)) if pnl_pct is not None else None

        positions.append({
            "id":          tid,
            "symbol":      sym,
            "signal":      sig,
            "setup_score": score,
            "entry_price": ep,
            "entry_ts":    ets_dt.isoformat(),
            "age_seconds": int(age_s),
            "stake_usd":   float(stake),
            "tp_pct":      float(tp_pct),
            "sl_pct":      float(sl_pct),
            "tp_price":    float(tp_p),
            "sl_price":    float(sl_p),
            "live_price":  live,
            "pnl_pct":     round(pnl_pct, 3) if pnl_pct is not None else None,
            "pnl_usd":     round(pnl_usd, 2) if pnl_usd is not None else None,
        })

    return {
        "positions":  positions,
        "n_open":     len(positions),
        "free_slots": _tb.MAX_TRADES - len(positions),
        "ts":         datetime.now(timezone.utc).isoformat(),
    }


@app.get("/testbot/history")
def testbot_history(
    limit:  int = 100,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Gesloten trades — meest recent eerst."""
    auth(x_api_key)
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("""
        SELECT id, symbol, signal, setup_score,
               entry_price, entry_ts, close_price, close_ts, close_reason,
               stake_usd, tp_pct, sl_pct,
               price_15m, price_1h, price_2h,
               pnl_pct, pnl_usd, fee_usd, net_pnl_usd
        FROM testbot_trades
        WHERE status = 'closed'
        ORDER BY close_ts DESC
        LIMIT ?
    """), (min(limit, 500),))
    rows = cur.fetchall()
    conn.close()

    def _pnl_at(ep, px):
        if ep and px:
            return round((float(px) - float(ep)) / float(ep) * 100, 3)
        return None

    trades = []
    for r in rows:
        (tid, sym, sig, score,
         ep, ets, cp, cts, reason,
         stake, tp_pct, sl_pct,
         p15m, p1h, p2h,
         pnl_p, pnl_u, fee_u, net_u) = r
        ep = float(ep)
        trades.append({
            "id":          tid,
            "symbol":      sym,
            "signal":      sig,
            "setup_score": score,
            "entry_price": ep,
            "entry_ts":    str(ets),
            "close_price": float(cp) if cp else None,
            "close_ts":    str(cts) if cts else None,
            "close_reason": reason,
            "stake_usd":   float(stake),
            "tp_pct":      float(tp_pct),
            "sl_pct":      float(sl_pct),
            "pnl_15m_pct": _pnl_at(ep, p15m),
            "pnl_1h_pct":  _pnl_at(ep, p1h),
            "pnl_2h_pct":  _pnl_at(ep, p2h),
            "pnl_pct":     float(pnl_p) if pnl_p is not None else None,
            "pnl_usd":     float(pnl_u) if pnl_u is not None else None,
            "fee_usd":     float(fee_u) if fee_u is not None else None,
            "net_pnl_usd": float(net_u) if net_u is not None else None,
        })

    # Totaalstats
    wins    = sum(1 for t in trades if (t["net_pnl_usd"] or 0) > 0)
    total_n = len(trades)
    total_net = sum(t["net_pnl_usd"] or 0 for t in trades)
    total_fee = sum(t["fee_usd"] or 0 for t in trades)

    return {
        "trades":       trades,
        "total":        total_n,
        "wins":         wins,
        "losses":       total_n - wins,
        "winrate_pct":  round(wins / total_n * 100, 1) if total_n else None,
        "total_net_usd": round(total_net, 2),
        "total_fee_usd": round(total_fee, 2),
        "ts":           datetime.now(timezone.utc).isoformat(),
    }


@app.get("/testbot/markers/{symbol}")
def testbot_markers(
    symbol: str,
    x_api_key: str | None = Header(default=None, alias="X-API-KEY"),
):
    """Testbot entry/exit markers voor chart.html — tijdstempels als Unix epoch."""
    auth(x_api_key)
    sym = "".join(c for c in symbol if c.isalnum()).upper()
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("""
        SELECT id, symbol, signal, setup_score, entry_price, entry_ts,
               close_price, close_ts, close_reason, stake_usd,
               tp_pct, sl_pct, tp_price, sl_price,
               pnl_pct, pnl_usd, fee_usd, net_pnl_usd, status
        FROM testbot_trades
        WHERE symbol = ?
        ORDER BY entry_ts ASC
    """), (sym,))
    rows = cur.fetchall()
    conn.close()

    def _to_unix(ts):
        if ts is None:
            return None
        if isinstance(ts, datetime):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp()), dt

    entries = []
    exits   = []
    for r in rows:
        (tid, sym2, sig, score, ep, ets,
         cp, cts, reason, stake,
         tp_pct, sl_pct, tp_p, sl_p,
         pnl_p, pnl_u, fee_u, net_u, status) = r
        try:
            ets_unix, ets_dt = _to_unix(ets)
        except Exception:
            continue

        entries.append({
            "trade_id":    tid,
            "time":        ets_unix,
            "entry_price": float(ep),
            "signal":      sig,
            "setup_score": float(score) if score is not None else None,
            "stake_usd":   float(stake),
            "tp_pct":      float(tp_pct),
            "sl_pct":      float(sl_pct),
            "status":      status,
        })

        if status == "closed" and cts:
            try:
                cts_unix, cts_dt = _to_unix(cts)
                dur_min = round((cts_dt - ets_dt).total_seconds() / 60, 1)
            except Exception:
                continue
            exits.append({
                "trade_id":     tid,
                "time":         cts_unix,
                "close_price":  float(cp) if cp else None,
                "close_reason": reason,
                "entry_price":  float(ep),
                "pnl_pct":      float(pnl_p)  if pnl_p  is not None else None,
                "pnl_usd":      float(pnl_u)  if pnl_u  is not None else None,
                "fee_usd":      float(fee_u)  if fee_u  is not None else None,
                "net_pnl_usd":  float(net_u)  if net_u  is not None else None,
                "duration_min": dur_min,
            })

    return {"entries": entries, "exits": exits, "symbol": sym}
