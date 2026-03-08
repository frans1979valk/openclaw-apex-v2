"""Jojo Analytics — lichte Python analytics service voor Jojo1."""
import os, json
from datetime import datetime, timezone
from collections import defaultdict
import numpy as np
import requests as req
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from db_compat import get_conn, dict_cursor, adapt_query, is_pg

app = FastAPI(title="Jojo Analytics")

BINANCE_BASE = os.getenv("BINANCE_BASE", "https://api.binance.com")
ORACLE_URL = os.getenv("ORACLE_URL", "http://market_oracle_sandbox:8095")
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
        conn = get_conn()
        cur = dict_cursor(conn)
        cur.execute(adapt_query(stripped))
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


# ══════════════════════════════════════════════════════════════════════════════
# GET /performance/unified — Uitgebreide performance analyse voor Jojo
# ══════════════════════════════════════════════════════════════════════════════

def _get_regime(ts, btc_regime_data: list) -> str:
    """Bepaal marktregime (bull/bear/chop) voor een gegeven timestamp op basis van BTC EMA200 (4h)."""
    for candle_ts, btc_price, ema200 in reversed(btc_regime_data):
        if candle_ts <= ts:
            diff_pct = (btc_price - ema200) / ema200 * 100
            if diff_pct > 3:
                return "bull"
            elif diff_pct < -3:
                return "bear"
            else:
                return "chop"
    return "unknown"


def _fmt_group(d: dict) -> dict:
    t = d["trades"]
    gross_profit = d["gross_profit"]
    gross_loss = d["gross_loss"]
    return {
        "trades": t,
        "wins": d["wins"],
        "losses": t - d["wins"],
        "winrate_pct": round(d["wins"] / t * 100, 1) if t > 0 else 0,
        "total_pnl_usdt": round(d["pnl"], 2),
        "avg_pnl_usdt": round(d["pnl"] / t, 2) if t > 0 else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
    }


def _group_default():
    return {"trades": 0, "wins": 0, "pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0}


def _update_group(g: dict, pnl: float):
    g["trades"] += 1
    g["wins"] += int(pnl > 0)
    g["pnl"] += pnl
    if pnl > 0:
        g["gross_profit"] += pnl
    else:
        g["gross_loss"] += abs(pnl)


@app.get("/performance/unified")
def unified_performance(days: int = 30, symbol: Optional[str] = None):
    """
    Unified performance breakdown per coin, per signaal, per marktregime.
    Query params:
      - days (int, default 30): hoeveel dagen terug
      - symbol (str, optioneel): filter op één coin (bijv. BTCUSDT)
    """
    try:
        conn = get_conn()
        cur = dict_cursor(conn)

        # 1. Demo balance samenvatting
        cur.execute("SELECT balance, peak_balance, total_trades, winning_trades FROM demo_balance WHERE id = 1")
        bal_row = cur.fetchone()
        bal = dict(bal_row) if bal_row else {}

        # 2. Gesloten trades uit demo_account (SELL/CLOSE acties met PnL)
        sym_clause = "AND symbol = %s" if is_pg() else "AND symbol = ?"
        time_clause = f"AND ts > NOW() - INTERVAL '{days} days'" if is_pg() else f"AND ts > datetime('now', '-{days} days')"
        params = [symbol.upper()] if symbol else []

        q = f"""
            SELECT ts, symbol, action, price, virtual_pnl_usdt, balance_after, signal
            FROM demo_account
            WHERE virtual_pnl_usdt IS NOT NULL
              AND virtual_pnl_usdt != 0
              {sym_clause if symbol else ""}
              {time_clause}
            ORDER BY ts
        """
        cur.execute(adapt_query(q), params)
        closed_rows = [dict(r) for r in cur.fetchall()]

        # 3. BTC 4h OHLCV voor regime berekening (90 dagen lookback)
        cur.execute(adapt_query("""
            SELECT ts, close FROM ohlcv_history
            WHERE symbol = 'BTCUSDT' AND interval = '4h'
            AND ts > datetime('now', '-90 days')
            ORDER BY ts
        """))
        btc_rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        # Bereken BTC EMA200 voor regime detectie
        btc_regime_data = []
        if btc_rows:
            btc_closes = np.array([float(r["close"]) for r in btc_rows])
            btc_ema200 = calc_ema(btc_closes, 200)
            for i, r in enumerate(btc_rows):
                if not np.isnan(btc_ema200[i]):
                    ts_val = r["ts"]
                    # Zorg voor timezone-aware timestamp
                    if hasattr(ts_val, "tzinfo") and ts_val.tzinfo is None:
                        ts_val = ts_val.replace(tzinfo=timezone.utc)
                    btc_regime_data.append((ts_val, float(btc_closes[i]), float(btc_ema200[i])))

        # Ensure alle timestamps timezone-aware zijn voor vergelijking
        def ensure_tz(ts):
            if hasattr(ts, "tzinfo") and ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts

        # 4. Aggregeer stats
        coin_stats = defaultdict(_group_default)
        signal_stats = defaultdict(_group_default)
        regime_stats = defaultdict(_group_default)
        recent_closed = []

        total_pnl = 0.0
        gross_profit = 0.0
        gross_loss = 0.0

        for r in closed_rows:
            pnl = float(r["virtual_pnl_usdt"])
            sym = r["symbol"]
            sig = r.get("signal") or "onbekend"
            trade_ts = ensure_tz(r["ts"]) if r["ts"] else None
            regime = _get_regime(trade_ts, btc_regime_data) if trade_ts and btc_regime_data else "unknown"

            total_pnl += pnl
            if pnl > 0:
                gross_profit += pnl
            else:
                gross_loss += abs(pnl)

            _update_group(coin_stats[sym], pnl)
            _update_group(signal_stats[sig], pnl)
            _update_group(regime_stats[regime], pnl)

            recent_closed.append({
                "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
                "symbol": sym,
                "signal": sig,
                "pnl_usdt": round(pnl, 2),
                "result": "win" if pnl > 0 else "loss",
                "regime": regime,
            })

        # Sorteer recent op datum (nieuwste eerst), max 20
        recent_closed.sort(key=lambda x: x["ts"], reverse=True)
        recent_closed = recent_closed[:20]

        total_closed = len(closed_rows)
        wins = sum(1 for r in closed_rows if float(r["virtual_pnl_usdt"]) > 0)
        balance = float(bal.get("balance", 0.0))
        peak = float(bal.get("peak_balance", balance))
        drawdown_pct = (balance - peak) / peak * 100 if peak > 0 else 0.0

        by_coin = sorted(
            [{"symbol": k, **_fmt_group(v)} for k, v in coin_stats.items()],
            key=lambda x: x["total_pnl_usdt"], reverse=True
        )
        by_signal = sorted(
            [{"signal": k, **_fmt_group(v)} for k, v in signal_stats.items()],
            key=lambda x: x["total_pnl_usdt"], reverse=True
        )
        by_regime = {k: _fmt_group(v) for k, v in regime_stats.items()}

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period_days": days,
            "filter_symbol": symbol.upper() if symbol else None,
            "summary": {
                "balance_usdt": round(balance, 2),
                "peak_balance_usdt": round(peak, 2),
                "drawdown_pct": round(drawdown_pct, 1),
                "total_trades_alltime": int(bal.get("total_trades", 0)),
                "winning_trades_alltime": int(bal.get("winning_trades", 0)),
                "closed_trades_in_period": total_closed,
                "wins_in_period": wins,
                "losses_in_period": total_closed - wins,
                "winrate_pct": round(wins / total_closed * 100, 1) if total_closed > 0 else 0,
                "total_pnl_usdt": round(total_pnl, 2),
                "avg_pnl_usdt": round(total_pnl / total_closed, 2) if total_closed > 0 else 0,
                "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
            },
            "by_coin": by_coin,
            "by_signal": by_signal,
            "by_regime": by_regime,
            "recent_closed": recent_closed,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# GET /features — Feature store: indicator snapshots per trade-entry
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/features")
def features_list(
    symbol: Optional[str] = None,
    signal: Optional[str] = None,
    regime: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
):
    """
    Haal feature snapshots op voor trade-entries.
    Query params:
      - symbol (str): filter op coin, bijv. BTCUSDT
      - signal (str): filter op signaaltype, bijv. BUY
      - regime (str): filter op btc_regime: bull/bear/chop/unknown
      - from_date (str): ISO datum, bijv. 2026-02-01
      - to_date   (str): ISO datum, bijv. 2026-03-01
      - limit (int): max rijen (default 100)
    """
    try:
        conn = get_conn()
        cur = dict_cursor(conn)

        clauses = []
        params  = []

        if symbol:
            clauses.append("symbol = %s" if is_pg() else "symbol = ?")
            params.append(symbol.upper())
        if signal:
            clauses.append("signal = %s" if is_pg() else "signal = ?")
            params.append(signal.upper())
        if regime:
            clauses.append("btc_regime = %s" if is_pg() else "btc_regime = ?")
            params.append(regime.lower())
        if from_date:
            clauses.append("ts >= %s" if is_pg() else "ts >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("ts <= %s" if is_pg() else "ts <= ?")
            params.append(to_date)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_val = min(max(1, limit), 500)
        ph = "%s" if is_pg() else "?"

        cur.execute(adapt_query(f"""
            SELECT id, ts, demo_trade_id, symbol, signal, entry_price,
                   rsi, macd_hist, adx, bb_width,
                   ema21, ema55, ema200, ema21_dist_pct, ema55_dist_pct, ema200_dist_pct,
                   crash_score, volume_usdt, atr,
                   tf_bias, tf_confirm_score, btc_regime,
                   blocker_context, pnl_1h_pct, pnl_4h_pct, outcome_status
            FROM trade_features
            {where}
            ORDER BY ts DESC
            LIMIT {ph}
        """), params + [limit_val])
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for r in rows:
            if r.get("ts") and hasattr(r["ts"], "isoformat"):
                r["ts"] = r["ts"].isoformat()
            if r.get("blocker_context") and isinstance(r["blocker_context"], str):
                try:
                    r["blocker_context"] = json.loads(r["blocker_context"])
                except Exception:
                    pass

        return {
            "count": len(rows),
            "limit": limit_val,
            "filters": {"symbol": symbol, "signal": signal, "regime": regime,
                        "from_date": from_date, "to_date": to_date},
            "trades": rows,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features/{trade_id}")
def feature_by_id(trade_id: int):
    """Haal de feature snapshot op voor één specifieke trade (via demo_account.id of trade_features.id)."""
    try:
        conn = get_conn()
        cur = dict_cursor(conn)
        ph = "%s" if is_pg() else "?"
        cur.execute(adapt_query(f"""
            SELECT * FROM trade_features
            WHERE demo_trade_id = {ph} OR id = {ph}
            ORDER BY ts DESC LIMIT 1
        """), (trade_id, trade_id))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"Geen feature record gevonden voor trade_id={trade_id}")
        result = dict(row)
        if result.get("ts") and hasattr(result["ts"], "isoformat"):
            result["ts"] = result["ts"].isoformat()
        if result.get("blocker_context") and isinstance(result["blocker_context"], str):
            try:
                result["blocker_context"] = json.loads(result["blocker_context"])
            except Exception:
                pass
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features-summary")
def features_summary(days: int = 30):
    """
    Geaggregeerde statistieken uit de feature store.
    Per regime, per signaal, per RSI-band — met gemiddelde 1h PnL en winrate.
    """
    try:
        conn = get_conn()
        cur = dict_cursor(conn)

        time_filter = f"AND ts > NOW() - INTERVAL '{days} days'" if is_pg() \
                      else f"AND ts > datetime('now', '-{days} days')"

        cur.execute(adapt_query(f"""
            SELECT btc_regime,
                   COUNT(*) as n,
                   AVG(rsi) as avg_rsi,
                   AVG(crash_score) as avg_crash_score,
                   AVG(ema200_dist_pct) as avg_ema200_dist,
                   COUNT(pnl_1h_pct) as n_closed,
                   AVG(pnl_1h_pct) as avg_pnl_1h,
                   100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(pnl_1h_pct), 0) as winrate_1h
            FROM trade_features
            WHERE 1=1 {time_filter}
            GROUP BY btc_regime ORDER BY n DESC
        """))
        by_regime = [dict(r) for r in cur.fetchall()]

        cur.execute(adapt_query(f"""
            SELECT signal,
                   COUNT(*) as n,
                   AVG(rsi) as avg_rsi,
                   COUNT(pnl_1h_pct) as n_closed,
                   AVG(pnl_1h_pct) as avg_pnl_1h,
                   100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(pnl_1h_pct), 0) as winrate_1h
            FROM trade_features
            WHERE 1=1 {time_filter}
            GROUP BY signal ORDER BY n DESC
        """))
        by_signal = [dict(r) for r in cur.fetchall()]

        cur.execute(adapt_query(f"""
            SELECT
                CASE
                    WHEN rsi < 25  THEN 'diep_oversold (<25)'
                    WHEN rsi < 35  THEN 'oversold (25-35)'
                    WHEN rsi < 50  THEN 'neutraal_laag (35-50)'
                    WHEN rsi < 65  THEN 'neutraal_hoog (50-65)'
                    ELSE                'overbought (>65)'
                END as rsi_band,
                COUNT(*) as n,
                AVG(rsi) as avg_rsi,
                COUNT(pnl_1h_pct) as n_closed,
                AVG(pnl_1h_pct) as avg_pnl_1h,
                100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(pnl_1h_pct), 0) as winrate_1h
            FROM trade_features
            WHERE rsi IS NOT NULL {time_filter}
            GROUP BY rsi_band ORDER BY avg_pnl_1h DESC NULLS LAST
        """))
        by_rsi_band = [dict(r) for r in cur.fetchall()]

        conn.close()

        def _r(rows):
            for row in rows:
                for k, v in row.items():
                    if isinstance(v, float):
                        row[k] = round(v, 3)
            return rows

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period_days": days,
            "by_regime": _r(by_regime),
            "by_signal": _r(by_signal),
            "by_rsi_band": _r(by_rsi_band),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
