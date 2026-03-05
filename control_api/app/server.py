import os, json, sqlite3, requests, secrets, random, time
import numpy as np
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = "/var/apex/apex.db"
STATE_PATH = "/var/apex/bot_state.json"
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
        conn = sqlite3.connect(DB_PATH)
        ensure_auth_tables(conn)
        cur = conn.cursor()
        cur.execute("SELECT expires_at FROM sessions WHERE token=?", (x_api_key,))
        row = cur.fetchone()
        conn.close()
        if row:
            exp = datetime.fromisoformat(row[0])
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

    conn = sqlite3.connect(DB_PATH)
    ensure_auth_tables(conn)
    # Verwijder oude codes voor dit email
    conn.execute("DELETE FROM otp_codes WHERE email=?", (email,))
    conn.execute("INSERT INTO otp_codes(email, code, expires_at) VALUES (?,?,?)", (email, code, expires))
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

    conn = sqlite3.connect(DB_PATH)
    ensure_auth_tables(conn)
    cur  = conn.cursor()
    cur.execute("SELECT code, expires_at FROM otp_codes WHERE email=? ORDER BY rowid DESC LIMIT 1", (email,))
    row = cur.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Geen code aangevraagd")

    stored_code, expires_at = row
    if datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
        conn.execute("DELETE FROM otp_codes WHERE email=?", (email,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=401, detail="Code verlopen")

    if stored_code != code:
        conn.close()
        raise HTTPException(status_code=401, detail="Onjuiste code")

    # Code correct → maak sessie aan (24 uur)
    token    = secrets.token_hex(32)
    sess_exp = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    conn.execute("DELETE FROM otp_codes WHERE email=?", (email,))
    conn.execute("INSERT INTO sessions(token, email, expires_at) VALUES (?,?,?)", (token, email, sess_exp))
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
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, ts, symbol, signal, active_signals,
                   entry_price, price_15m, price_1h, price_4h,
                   pnl_15m_pct, pnl_1h_pct, pnl_4h_pct, status
            FROM signal_performance
            ORDER BY id DESC LIMIT ?
        """, (limit,))
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
    conn = sqlite3.connect(DB_PATH)
    ensure_tables(conn)
    cur = conn.cursor()
    cur.execute("SELECT id, ts, agent, params_json, reason, status FROM proposals ORDER BY id DESC LIMIT 200")
    rows = cur.fetchall()
    conn.close()
    return [{"id":r[0],"ts":r[1],"agent":r[2],"params":json.loads(r[3]),"reason":r[4],"status":r[5]} for r in rows]

@app.post("/config/propose")
def propose(p: Proposal, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    conn = sqlite3.connect(DB_PATH)
    ensure_tables(conn)
    cur = conn.cursor()
    ts = datetime.now(timezone.utc).isoformat()
    cur.execute("INSERT INTO proposals(ts, agent, params_json, reason, status) VALUES (?, ?, ?, ?, 'pending')",
                (ts, p.agent, json.dumps(p.params, ensure_ascii=False), p.reason))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return {"ok": True, "proposal_id": pid}

@app.post("/proposals/{proposal_id}/apply")
def apply_proposal(proposal_id: int, x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    auth(x_api_key)
    conn = sqlite3.connect(DB_PATH)
    ensure_tables(conn)
    cur = conn.cursor()
    cur.execute("UPDATE proposals SET status='applied' WHERE id=?", (proposal_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "applied": proposal_id}

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
    conn.execute("""CREATE TABLE IF NOT EXISTS historical_backtest(
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
    )""")
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
    conn.executemany("""
        INSERT INTO historical_backtest
          (run_ts, symbol, interval, months, candle_ts, signal, active_signals,
           entry_price, price_1h, price_4h, price_24h,
           pnl_1h_pct, pnl_4h_pct, pnl_24h_pct)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [(r["run_ts"], r["symbol"], r["interval"], r["months"], r["candle_ts"],
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
        conn = sqlite3.connect(DB_PATH)
        _ensure_hist_table(conn)
        conn.execute("DELETE FROM historical_backtest WHERE symbol=? AND interval=? AND months=?",
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
    conn = sqlite3.connect(DB_PATH)
    _ensure_hist_table(conn)
    cur = conn.cursor()
    sym = symbol.upper()
    if signal_filter:
        cur.execute("""
            SELECT candle_ts, signal, active_signals, entry_price,
                   pnl_1h_pct, pnl_4h_pct, pnl_24h_pct
            FROM historical_backtest
            WHERE symbol=? AND interval=? AND months=? AND signal=?
            ORDER BY candle_ts DESC LIMIT ?
        """, (sym, interval, months, signal_filter.upper(), limit))
    else:
        cur.execute("""
            SELECT candle_ts, signal, active_signals, entry_price,
                   pnl_1h_pct, pnl_4h_pct, pnl_24h_pct
            FROM historical_backtest
            WHERE symbol=? AND interval=? AND months=?
            ORDER BY candle_ts DESC LIMIT ?
        """, (sym, interval, months, limit))
    rows = cur.fetchall()
    conn.close()
    return [{"ts": r[0], "signal": r[1], "active": json.loads(r[2] or "[]"),
             "entry": r[3], "pnl_1h": r[4], "pnl_4h": r[5], "pnl_24h": r[6]}
            for r in rows]


@app.get("/balance")
def get_balance(x_api_key: str | None = Header(default=None, alias="X-API-KEY")):
    """Toon demo account balans overzicht op basis van order history."""
    auth(x_api_key)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Totaal orders
        cur.execute("SELECT COUNT(*), SUM(CAST(size AS REAL) * price) FROM orders")
        row = cur.fetchone()
        total_orders = row[0] or 0
        total_volume = round(row[1] or 0.0, 2)
        # Recente orders
        cur.execute("""
            SELECT ts, symbol, side, size, price FROM orders
            ORDER BY id DESC LIMIT 10
        """)
        recent = [{"ts": r[0], "symbol": r[1], "side": r[2], "size": r[3], "price": r[4]}
                  for r in cur.fetchall()]
        # Signal performance stats
        cur.execute("""
            SELECT COUNT(*), AVG(pnl_1h_pct),
                   AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100
            FROM signal_performance WHERE status='closed'
        """)
        sp = cur.fetchone()
        conn.close()
        return {
            "account_type":   "demo",
            "exchange":       "BloFin Demo",
            "demo_start_usdt": 10000.0,
            "total_orders":   total_orders,
            "total_volume_usdt": total_volume,
            "signals_evaluated": sp[0] or 0,
            "avg_pnl_1h_pct": round(sp[1] or 0, 3),
            "win_rate_pct":   round(sp[2] or 0, 1),
            "recent_orders":  recent,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
