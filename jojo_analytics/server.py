"""Jojo Analytics — lichte Python analytics service voor Jojo1."""
import os, json, sqlite3
import numpy as np
import requests as req
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Jojo Analytics")

BINANCE_BASE = os.getenv("BINANCE_BASE", "https://api.binance.com")
ORACLE_URL = os.getenv("ORACLE_URL", "http://market_oracle_sandbox:8095")
DB_PATH = "/var/apex/apex.db"
MAX_ROWS = 200


# ══════════════════════════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════════════════════════

class IndicatorRequest(BaseModel):
    symbol: str
    interval: str = "1h"
    limit: int = 200

class QueryRequest(BaseModel):
    sql: str

class OracleRequest(BaseModel):
    action: str  # "scan" of "event"
    text: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "service": "jojo_analytics"}


# ══════════════════════════════════════════════════════════════════════════════
# POST /indicators — Technische indicatoren via Binance OHLCV
# ══════════════════════════════════════════════════════════════════════════════

def fetch_ohlcv(symbol: str, interval: str, limit: int) -> dict:
    r = req.get(f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
                timeout=10)
    r.raise_for_status()
    data = r.json()
    return {
        "open":   np.array([float(c[1]) for c in data]),
        "high":   np.array([float(c[2]) for c in data]),
        "low":    np.array([float(c[3]) for c in data]),
        "close":  np.array([float(c[4]) for c in data]),
        "volume": np.array([float(c[5]) for c in data]),
    }


def calc_ema(values: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(values), np.nan)
    if len(values) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(values[:period])
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def calc_sma(values: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        result[i] = np.mean(values[i - period + 1:i + 1])
    return result


def calc_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    result = np.full(len(close), np.nan)
    if len(close) < period + 1:
        return result
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - 100 / (1 + rs)
    return result


def calc_macd(close: np.ndarray, fast=12, slow=26, signal=9) -> dict:
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    valid_mask = ~np.isnan(macd_line)
    valid_vals = macd_line[valid_mask]
    sig_line = np.full(len(close), np.nan)
    if len(valid_vals) >= signal:
        sig_ema = calc_ema(valid_vals, signal)
        sig_line[valid_mask] = np.where(np.isnan(sig_ema), np.nan, sig_ema)
    hist = macd_line - sig_line
    return {"macd": macd_line, "signal": sig_line, "hist": hist}


def calc_bollinger(close: np.ndarray, period=20, std_dev=2.0) -> dict:
    mid = calc_sma(close, period)
    upper = np.full(len(close), np.nan)
    lower = np.full(len(close), np.nan)
    width = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        sd = np.std(close[i - period + 1:i + 1])
        upper[i] = mid[i] + std_dev * sd
        lower[i] = mid[i] - std_dev * sd
        width[i] = (upper[i] - lower[i]) / mid[i] * 100 if mid[i] > 0 else 0
    return {"upper": upper, "lower": lower, "mid": mid, "width": width}


def calc_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period=14) -> np.ndarray:
    n = len(close)
    if n < period * 2:
        return np.full(n, np.nan)

    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    def wilder_smooth(vals, p):
        s = [np.mean(vals[:p])]
        for v in vals[p:]:
            s.append((s[-1] * (p - 1) + v) / p)
        return np.array(s)

    atr_s = wilder_smooth(tr, period)
    pdm_s = wilder_smooth(plus_dm, period)
    mdm_s = wilder_smooth(minus_dm, period)

    pdi = np.where(atr_s > 0, 100 * pdm_s / atr_s, 0)
    mdi = np.where(atr_s > 0, 100 * mdm_s / atr_s, 0)
    denom = pdi + mdi
    dx = np.where(denom > 0, 100 * np.abs(pdi - mdi) / denom, 0)

    adx_s = wilder_smooth(dx, period)
    result = np.full(n, np.nan)
    result[-len(adx_s):] = adx_s
    return result


def calc_stoch_rsi(close: np.ndarray, rsi_period=14, stoch_period=14, k_smooth=3) -> dict:
    rsi_vals = calc_rsi(close, rsi_period)
    valid = rsi_vals[~np.isnan(rsi_vals)]
    if len(valid) < stoch_period:
        return {"k": None, "d": None}
    k_vals = []
    for i in range(stoch_period - 1, len(valid)):
        window = valid[i - stoch_period + 1:i + 1]
        mn, mx = window.min(), window.max()
        k_vals.append(50.0 if mx == mn else (valid[i] - mn) / (mx - mn) * 100)
    k_arr = np.array(k_vals)
    d_arr = calc_sma(k_arr, k_smooth) if len(k_arr) >= k_smooth else k_arr
    return {
        "k": round(float(k_arr[-1]), 1) if len(k_arr) > 0 else None,
        "d": round(float(d_arr[~np.isnan(d_arr)][-1]), 1) if np.any(~np.isnan(d_arr)) else None,
    }


def safe_round(val, decimals=4):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return round(float(val), decimals)


@app.post("/indicators")
def indicators(body: IndicatorRequest):
    try:
        ohlcv = fetch_ohlcv(body.symbol, body.interval, body.limit)
        c = ohlcv["close"]
        h = ohlcv["high"]
        lo = ohlcv["low"]

        rsi = calc_rsi(c)
        macd_data = calc_macd(c)
        bb = calc_bollinger(c)
        adx = calc_adx(h, lo, c)
        ema21 = calc_ema(c, 21)
        ema55 = calc_ema(c, 55)
        ema200 = calc_ema(c, 200)
        srsi = calc_stoch_rsi(c)

        cur_rsi = safe_round(rsi[-1], 1)
        cur_macd_h = safe_round(macd_data["hist"][-1], 6)
        cur_bb_width = safe_round(bb["width"][-1], 2)
        cur_adx = safe_round(adx[-1], 1)
        cur_price = float(c[-1])
        e21 = safe_round(ema21[-1], 6)
        e55 = safe_round(ema55[-1], 6)
        e200 = safe_round(ema200[-1], 6)

        ema_bull = (e21 is not None and e55 is not None and e200 is not None
                    and cur_price > e21 > e55 > e200)

        # BB positie
        bb_pos = "mid"
        if bb["upper"][-1] is not None and not np.isnan(bb["upper"][-1]):
            if cur_price >= float(bb["upper"][-1]):
                bb_pos = "upper"
            elif cur_price <= float(bb["lower"][-1]):
                bb_pos = "lower"

        # MACD signaal
        macd_signal = "neutral"
        if cur_macd_h is not None:
            macd_signal = "bullish" if cur_macd_h > 0 else "bearish"

        # Advies
        advies = "HOLD"
        if cur_rsi is not None:
            if cur_rsi < 30 and macd_signal == "bullish":
                advies = "BUY_CANDIDATE"
            elif cur_rsi < 25:
                advies = "OVERSOLD"
            elif cur_rsi > 70 and macd_signal == "bearish":
                advies = "SELL_CANDIDATE"
            elif cur_rsi > 75:
                advies = "OVERBOUGHT"
            elif ema_bull and cur_adx is not None and cur_adx > 25:
                advies = "TREND_BULL"

        # Laatste 5 waarden
        def last5(arr):
            valid = arr[~np.isnan(arr)]
            return [round(float(v), 4) for v in valid[-5:]]

        return {
            "symbol": body.symbol.upper(),
            "interval": body.interval,
            "price": round(cur_price, 6),
            "rsi": cur_rsi,
            "macd_hist": cur_macd_h,
            "macd_signal": macd_signal,
            "bb_width": cur_bb_width,
            "bb_position": bb_pos,
            "adx": cur_adx,
            "stoch_rsi_k": srsi["k"],
            "stoch_rsi_d": srsi["d"],
            "ema21": e21,
            "ema55": e55,
            "ema200": e200,
            "ema_bull": ema_bull,
            "advies": advies,
            "rsi_last5": last5(rsi),
            "macd_hist_last5": last5(macd_data["hist"]),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# POST /query — SELECT-only DB queries
# ══════════════════════════════════════════════════════════════════════════════

FORBIDDEN_KW = ("DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH", "DETACH", "PRAGMA")

@app.post("/query")
def db_query(body: QueryRequest):
    stripped = body.sql.strip().rstrip(";").strip()
    if not stripped.upper().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Alleen SELECT queries zijn toegestaan.")
    upper = stripped.upper()
    for kw in FORBIDDEN_KW:
        if kw in upper:
            raise HTTPException(status_code=400, detail=f"Verboden keyword: {kw}")

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(stripped)
        rows = cur.fetchmany(MAX_ROWS)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        result = [dict(r) for r in rows]
        conn.close()
        return {"rows": result, "columns": columns, "count": len(result), "truncated": len(result) >= MAX_ROWS}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# POST /oracle — Market Oracle proxy
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/oracle")
def oracle(body: OracleRequest):
    try:
        if body.action == "scan":
            r = req.get(f"{ORACLE_URL}/scan", timeout=30)
            r.raise_for_status()
            return r.json()
        elif body.action == "event":
            if not body.text:
                raise HTTPException(status_code=400, detail="text is vereist voor action=event")
            r = req.post(f"{ORACLE_URL}/run_event", json={"event": body.text}, timeout=30)
            r.raise_for_status()
            return r.json()
        else:
            raise HTTPException(status_code=400, detail=f"Onbekende action: {body.action}. Gebruik 'scan' of 'event'.")
    except req.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Oracle niet bereikbaar: {e}")
