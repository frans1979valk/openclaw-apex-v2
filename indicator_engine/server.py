"""Indicator Engine — historische data import, indicator berekening en pattern matching."""
import os, json, logging, time
from datetime import datetime, timezone, timedelta
from typing import Optional
from collections import deque
import numpy as np
import requests as req
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
import talib
from db_compat import get_conn, adapt_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("indicator_engine")

app = FastAPI(title="Indicator Engine")

BINANCE_BASE = os.getenv("BINANCE_BASE", "https://api.binance.com")
SAFE_COINS = os.getenv("SAFE_COINS",
    "BTCUSDT,ETHUSDT,SOLUSDT,AAVEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,"
    "UNIUSDT,LTCUSDT,DOGEUSDT,XRPUSDT,BNBUSDT,ADAUSDT,ATOMUSDT,"
    "ARBUSDT,APTUSDT,SEIUSDT"
).split(",")
UPDATE_INTERVAL_MINUTES = int(os.getenv("UPDATE_INTERVAL_MINUTES", "60"))

# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv_data (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    interval VARCHAR(5) NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DECIMAL, high DECIMAL, low DECIMAL, close DECIMAL, volume DECIMAL,
    UNIQUE(symbol, interval, ts)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_sym_int_ts ON ohlcv_data(symbol, interval, ts DESC);

CREATE TABLE IF NOT EXISTS indicators_data (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    interval VARCHAR(5) NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    rsi DECIMAL, macd_hist DECIMAL,
    bb_width DECIMAL, bb_position VARCHAR(15),
    ema21 DECIMAL, ema55 DECIMAL, ema200 DECIMAL,
    ema_bull BOOLEAN,
    adx DECIMAL, stoch_rsi_k DECIMAL, stoch_rsi_d DECIMAL,
    atr DECIMAL, volume_ratio DECIMAL,
    rsi_zone VARCHAR(20),
    UNIQUE(symbol, interval, ts)
);
CREATE INDEX IF NOT EXISTS idx_ind_sym_int_ts ON indicators_data(symbol, interval, ts DESC);

CREATE TABLE IF NOT EXISTS pattern_results (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    interval VARCHAR(5) NOT NULL,
    rsi_zone VARCHAR(20),
    macd_direction VARCHAR(10),
    bb_position VARCHAR(15),
    ema_alignment VARCHAR(10),
    adx_strength VARCHAR(10),
    btc_trend VARCHAR(10),
    pnl_1h DECIMAL,
    pnl_4h DECIMAL,
    was_win BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_pat_lookup ON pattern_results(symbol, rsi_zone, macd_direction, bb_position, ema_alignment, btc_trend);
"""


def init_schema():
    conn = get_conn()
    cur = conn.cursor()
    for stmt in SCHEMA_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            cur.execute(stmt)
    conn.commit()
    conn.close()
    log.info("Schema geïnitialiseerd")


# ── Binance data ophalen ──────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str, limit: int = 500) -> list:
    r = req.get(f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=15)
    r.raise_for_status()
    return r.json()


def store_ohlcv(symbol: str, interval: str, rows: list) -> int:
    if not rows:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    count = 0
    for row in rows:
        ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
        try:
            cur.execute(adapt_query("""
                INSERT INTO ohlcv_data(symbol, interval, ts, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING
            """), (symbol, interval, ts, float(row[1]), float(row[2]),
                   float(row[3]), float(row[4]), float(row[5])))
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count


# ── Indicator berekening ──────────────────────────────────────────────────────

def rsi_zone(rsi: float) -> str:
    if rsi < 25:   return "oversold"
    if rsi < 45:   return "neutral_low"
    if rsi < 60:   return "neutral_high"
    return "overbought"


def compute_indicators(symbol: str, interval: str, limit: int = 50000) -> int:
    """Bereken en sla indicatoren op voor alle aanwezige OHLCV candles."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(adapt_query("""
        SELECT ts, open, high, low, close, volume
        FROM ohlcv_data
        WHERE symbol=? AND interval=?
        ORDER BY ts ASC
        LIMIT ?
    """), (symbol, interval, limit))
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 50:
        return 0

    ts_list = [r[0] for r in rows]
    closes  = np.array([float(r[4]) for r in rows], dtype=float)
    highs   = np.array([float(r[2]) for r in rows], dtype=float)
    lows    = np.array([float(r[3]) for r in rows], dtype=float)
    vols    = np.array([float(r[5]) for r in rows], dtype=float)

    rsi_arr    = talib.RSI(closes, 14)
    ema21_arr  = talib.EMA(closes, 21)
    ema55_arr  = talib.EMA(closes, 55)
    ema200_arr = talib.EMA(closes, 200)
    macd_, _, macd_hist_arr = talib.MACD(closes, 12, 26, 9)
    bb_upper, bb_mid, bb_lower = talib.BBANDS(closes, 20)
    adx_arr    = talib.ADX(highs, lows, closes, 14)
    atr_arr    = talib.ATR(highs, lows, closes, 14)
    stoch_k, stoch_d = talib.STOCHRSI(closes, 14, 3, 3)

    avg_vol_arr = talib.SMA(vols, 20)

    conn = get_conn()
    cur = conn.cursor()
    count = 0
    for i in range(len(rows)):
        if any(np.isnan(x) for x in [rsi_arr[i], ema21_arr[i], ema55_arr[i], macd_hist_arr[i]]):
            continue
        ts = ts_list[i]

        # BB positie
        bb_w = float((bb_upper[i] - bb_lower[i]) / bb_mid[i] * 100) if not np.isnan(bb_upper[i]) else None
        if bb_w is not None and not np.isnan(bb_lower[i]):
            if closes[i] < bb_lower[i]:   bb_pos = "below_lower"
            elif closes[i] > bb_upper[i]: bb_pos = "above_upper"
            elif closes[i] < bb_mid[i]:   bb_pos = "lower_half"
            else:                          bb_pos = "upper_half"
        else:
            bb_pos = None

        ema_bull = bool(ema21_arr[i] > ema55_arr[i]) if not np.isnan(ema21_arr[i]) else None
        vol_ratio = float(vols[i] / avg_vol_arr[i]) if not np.isnan(avg_vol_arr[i]) and avg_vol_arr[i] > 0 else None

        try:
            cur.execute(adapt_query("""
                INSERT INTO indicators_data
                (symbol, interval, ts, rsi, macd_hist, bb_width, bb_position,
                 ema21, ema55, ema200, ema_bull, adx, stoch_rsi_k, stoch_rsi_d,
                 atr, volume_ratio, rsi_zone)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT DO NOTHING
            """), (
                symbol, interval, ts,
                round(float(rsi_arr[i]), 2),
                round(float(macd_hist_arr[i]), 6),
                round(bb_w, 3) if bb_w else None,
                bb_pos,
                round(float(ema21_arr[i]), 4),
                round(float(ema55_arr[i]), 4),
                round(float(ema200_arr[i]), 4) if not np.isnan(ema200_arr[i]) else None,
                ema_bull,
                round(float(adx_arr[i]), 2) if not np.isnan(adx_arr[i]) else None,
                round(float(stoch_k[i]), 2) if not np.isnan(stoch_k[i]) else None,
                round(float(stoch_d[i]), 2) if not np.isnan(stoch_d[i]) else None,
                round(float(atr_arr[i]), 6) if not np.isnan(atr_arr[i]) else None,
                round(vol_ratio, 3) if vol_ratio else None,
                rsi_zone(float(rsi_arr[i])),
            ))
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count


# ── Pattern resultaten vullen ─────────────────────────────────────────────────

def build_pattern_results(symbol: str, interval: str = "1h"):
    """Koppel indicators aan toekomstige prijzen → vul pattern_results tabel."""
    conn = get_conn()
    cur = conn.cursor()
    # Haal indicator + prijs data samen op, gesorteerd op tijd
    cur.execute(adapt_query("""
        SELECT i.ts, i.rsi_zone, i.bb_position, i.ema_bull, i.adx, i.macd_hist,
               o.close
        FROM indicators_data i
        JOIN ohlcv_data o ON o.symbol=i.symbol AND o.interval=i.interval AND o.ts=i.ts
        WHERE i.symbol=? AND i.interval=?
        ORDER BY i.ts ASC
    """), (symbol, interval))
    rows = cur.fetchall()

    if len(rows) < 10:
        conn.close()
        return 0

    # Bouw price lookup voor toekomstige PnL
    prices = {r[0]: float(r[6]) for r in rows}
    ts_sorted = sorted(prices.keys())

    def future_price(ts, hours):
        target = ts + timedelta(hours=hours)
        # vind dichtstbijzijnde timestamp
        candidates = [t for t in ts_sorted if t >= target]
        if candidates:
            return prices[candidates[0]]
        return None

    # BTC trend ophalen
    cur.execute(adapt_query("""
        SELECT ts, ema_bull FROM indicators_data
        WHERE symbol='BTCUSDT' AND interval=?
        ORDER BY ts ASC
    """), (interval,))
    btc_rows = cur.fetchall()
    btc_trend_map = {r[0]: ("bull" if r[1] else "bear") for r in btc_rows if r[1] is not None}

    count = 0
    for row in rows:
        ts, rsi_z, bb_pos, ema_bull, adx, macd_hist, close = row
        close = float(close) if close is not None else None
        adx = float(adx) if adx is not None else 0.0
        macd_hist = float(macd_hist) if macd_hist is not None else 0.0
        if not all([rsi_z, bb_pos]):
            continue

        macd_dir = "bullish" if (macd_hist or 0) > 0 else "bearish"
        ema_align = "bull" if ema_bull else "bear"
        adx_str = "strong" if (adx or 0) > 25 else "weak"
        btc_trend = btc_trend_map.get(ts, "neutral")

        p1h = future_price(ts, 1)
        p4h = future_price(ts, 4)
        if p1h is None:
            continue

        pnl_1h = round((p1h / close - 1) * 100, 3) if close else None
        pnl_4h = round((p4h / close - 1) * 100, 3) if p4h and close else None
        was_win = (pnl_1h or 0) > 0

        try:
            cur.execute(adapt_query("""
                INSERT INTO pattern_results
                (symbol, ts, interval, rsi_zone, macd_direction, bb_position,
                 ema_alignment, adx_strength, btc_trend, pnl_1h, pnl_4h, was_win)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT DO NOTHING
            """), (symbol, ts, interval, rsi_z, macd_dir, bb_pos,
                   ema_align, adx_str, btc_trend, pnl_1h, pnl_4h, was_win))
            count += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return count


# ── Pattern lookup ────────────────────────────────────────────────────────────

def lookup_pattern(symbol: str, rsi_z: str, macd_dir: str, bb_pos: str,
                   ema_align: str, btc_trend: str, min_trades: int = 8) -> dict:
    """Zoek historische precedenten voor het huidige patroon."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(adapt_query("""
        SELECT COUNT(*) as n,
               AVG(pnl_1h) as avg_pnl_1h,
               AVG(pnl_4h) as avg_pnl_4h,
               AVG(CASE WHEN was_win THEN 1.0 ELSE 0.0 END) * 100 as win_rate,
               MIN(pnl_1h) as worst_1h
        FROM pattern_results
        WHERE symbol=?
          AND rsi_zone=?
          AND macd_direction=?
          AND bb_position=?
          AND ema_alignment=?
          AND btc_trend=?
    """), (symbol, rsi_z, macd_dir, bb_pos, ema_align, btc_trend))
    row = cur.fetchone()
    conn.close()

    if not row or not row[0] or int(row[0]) < min_trades:
        return {"found": False, "precedenten": int(row[0]) if row and row[0] else 0}

    return {
        "found": True,
        "precedenten": int(row[0]),
        "avg_pnl_1h": round(float(row[1] or 0), 3),
        "avg_pnl_4h": round(float(row[2] or 0), 3),
        "win_rate": round(float(row[3] or 0), 1),
        "worst_1h": round(float(row[4] or 0), 3),
    }


# ── Historische import ────────────────────────────────────────────────────────

def import_history(symbol: str, interval: str = "1h", months: int = 12):
    """Importeer historische OHLCV data (tot 12 maanden terug) via meerdere Binance calls."""
    total = 0
    end_time = None
    for _ in range(months * 3):  # max ~3 calls per maand voor 1h data
        params = {"symbol": symbol, "interval": interval, "limit": 1000}
        if end_time:
            params["endTime"] = end_time
        try:
            r = req.get(f"{BINANCE_BASE}/api/v3/klines", params=params, timeout=20)
            r.raise_for_status()
            rows = r.json()
        except Exception as e:
            log.error(f"Import fout {symbol} {interval}: {e}")
            break
        if not rows:
            break
        n = store_ohlcv(symbol, interval, rows)
        total += n
        end_time = rows[0][0] - 1  # één ms voor de vroegste candle
        time.sleep(0.3)
        if len(rows) < 100:
            break
    return total


def full_history_import():
    """Importeer 12 maanden OHLCV voor alle SAFE_COINS op 1h en 4h."""
    log.info("Start historische import...")
    for symbol in SAFE_COINS:
        symbol = symbol.strip()
        if not symbol:
            continue
        for interval in ["1h", "4h"]:
            try:
                n = import_history(symbol, interval, months=12)
                ind_n = compute_indicators(symbol, interval)
                pat_n = build_pattern_results(symbol, interval)
                log.info(f"Import {symbol} {interval}: {n} candles, {ind_n} indicators, {pat_n} patterns")
            except Exception as e:
                log.error(f"Import fout {symbol} {interval}: {e}")


def incremental_update():
    """Haal nieuwe candles op en herbereken indicators voor alle coins."""
    log.info("Incrementele update...")
    for symbol in SAFE_COINS:
        symbol = symbol.strip()
        if not symbol:
            continue
        for interval in ["1h", "4h"]:
            try:
                rows = fetch_ohlcv(symbol, interval, limit=50)
                store_ohlcv(symbol, interval, rows)
                compute_indicators(symbol, interval, limit=300)
            except Exception as e:
                log.error(f"Update fout {symbol} {interval}: {e}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler()
_import_done = False


@app.on_event("startup")
def startup():
    init_schema()
    scheduler.add_job(incremental_update, "interval",
                      minutes=UPDATE_INTERVAL_MINUTES,
                      id="incremental_update",
                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60))
    # Coin auto-discovery: elke 30 minuten
    scheduler.add_job(_check_new_coins, "interval",
                      minutes=30,
                      id="coin_watcher",
                      next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    # Historical enrichment: eenmalig 2 minuten na start
    scheduler.add_job(_run_historical_enrich, "date",
                      run_date=datetime.now(timezone.utc) + timedelta(minutes=2),
                      id="initial_enrich")
    scheduler.start()
    log.info(f"Scheduler gestart: update elke {UPDATE_INTERVAL_MINUTES} min, coin-watcher elke 30 min")
    _start_ws_feed()


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown()
    _ws_stop()


# ── API Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
    return {"status": "ok", "service": "indicator_engine", "scheduled_jobs": jobs}


class ImportRequest(BaseModel):
    symbols: list[str] = []
    months: int = 12
    intervals: list[str] = ["1h", "4h"]


@app.post("/import")
def trigger_import(req_body: ImportRequest, background_tasks: BackgroundTasks):
    """Start historische import in de achtergrond."""
    coins = [s.strip() for s in req_body.symbols] if req_body.symbols else SAFE_COINS

    def _do_import():
        for sym in coins:
            for iv in req_body.intervals:
                try:
                    n = import_history(sym, iv, req_body.months)
                    ind_n = compute_indicators(sym, iv)
                    pat_n = build_pattern_results(sym, iv)
                    log.info(f"Import {sym} {iv}: {n} candles, {ind_n} ind, {pat_n} patterns")
                except Exception as e:
                    log.error(f"Import fout {sym} {iv}: {e}")

    background_tasks.add_task(_do_import)
    return {"ok": True, "message": f"Import gestart voor {len(coins)} coins"}


class RecomputeRequest(BaseModel):
    symbols: list[str] = []
    intervals: list[str] = ["1h", "4h"]


@app.post("/recompute")
def trigger_recompute(req_body: RecomputeRequest, background_tasks: BackgroundTasks):
    """Herbereken indicators + pattern_results voor bestaande OHLCV data (geen nieuwe download)."""
    coins = [s.strip() for s in req_body.symbols] if req_body.symbols else SAFE_COINS

    def _do_recompute():
        for sym in coins:
            for iv in req_body.intervals:
                try:
                    ind_n = compute_indicators(sym, iv)
                    pat_n = build_pattern_results(sym, iv)
                    log.info(f"Recompute {sym} {iv}: {ind_n} indicators, {pat_n} patterns")
                except Exception as e:
                    log.error(f"Recompute fout {sym} {iv}: {e}")

    background_tasks.add_task(_do_recompute)
    return {"ok": True, "message": f"Recompute gestart voor {len(coins)} coins, intervals={req_body.intervals}"}


class StrategyBacktestRequest(BaseModel):
    symbols: list[str] = ["BTCUSDT", "ETHUSDT"]
    interval: str = "1h"
    # Strategy parameters
    btc_filter: bool = True          # blokkeer altcoin longs als BTC bearish
    rsi_buy_threshold: float = 30.0  # max RSI voor entry
    rsi_chop_max: float = 55.0       # chop zone: skip RSI tussen threshold en chop_max
    rsi_sell_threshold: float = 65.0 # exit bij RSI > deze waarde
    stoploss_pct: float = 2.0        # stoploss %
    takeprofit_pct: float = 4.5      # take profit %
    max_positions: int = 3           # max gelijktijdige posities
    # Coin-specifieke overrides (sym -> rsi_threshold)
    coin_rsi_overrides: dict = {}


@app.post("/backtest/strategy")
def backtest_strategy(req_body: StrategyBacktestRequest):
    """
    Backtest een strategie-configuratie op historische indicators_data.
    Simuleert de apex_engine logica met configureerbare parameters.
    Geeft win_rate, total_pnl, max_drawdown, profit_factor terug.
    """
    conn = get_conn()
    cur = conn.cursor()

    # BTC trend tijdlijn ophalen voor de filter
    btc_trend: dict = {}
    if req_body.btc_filter:
        cur.execute(adapt_query("""
            SELECT ts, ema_bull, rsi FROM indicators_data
            WHERE symbol='BTCUSDT' AND interval=?
            ORDER BY ts ASC
        """), (req_body.interval,))
        for r in cur.fetchall():
            ema_bull = r[1]
            rsi_val = float(r[2] or 50)
            btc_trend[r[0]] = (bool(ema_bull) and rsi_val >= 45)

    all_trades = []
    per_coin = {}

    for sym in req_body.symbols:
        rsi_limit = req_body.coin_rsi_overrides.get(sym, req_body.rsi_buy_threshold)

        cur.execute(adapt_query("""
            SELECT i.ts, i.rsi, i.ema_bull, i.macd_hist, i.rsi_zone, o.close
            FROM indicators_data i
            JOIN ohlcv_data o ON o.symbol=i.symbol AND o.interval=i.interval AND o.ts=i.ts
            WHERE i.symbol=? AND i.interval=?
            ORDER BY i.ts ASC
        """), (sym, req_body.interval))
        rows = cur.fetchall()

        if len(rows) < 50:
            continue

        trades = []
        position = None  # {"entry": price, "ts": ts}
        open_positions = 0

        for row in rows:
            ts, rsi, ema_bull, macd_hist, rsi_z, close = row
            if close is None:
                continue
            close = float(close)
            rsi = float(rsi or 50)
            macd_hist = float(macd_hist or 0)

            # Exit check (altijd eerst)
            if position is not None:
                entry = position["entry"]
                pnl = (close / entry - 1) * 100
                if (pnl >= req_body.takeprofit_pct or
                        pnl <= -req_body.stoploss_pct or
                        rsi > req_body.rsi_sell_threshold):
                    trades.append(round(pnl, 3))
                    position = None
                    open_positions -= 1
                    continue

            # Entry check
            if position is None:
                # BTC filter
                if req_body.btc_filter and sym != "BTCUSDT":
                    # Zoek dichtstbijzijnde BTC trend waarde
                    btc_ok = btc_trend.get(ts)
                    if btc_ok is None:
                        # Neem meest recente BTC waarde voor dit tijdstip
                        candidates = [t for t in btc_trend if t <= ts]
                        btc_ok = btc_trend[candidates[-1]] if candidates else True
                    if not btc_ok:
                        continue

                # Max posities
                if open_positions >= req_body.max_positions:
                    continue

                # RSI entry check
                if rsi > rsi_limit:
                    continue

                # Chop zone: skip als RSI tussen buy_threshold en chop_max
                if rsi_limit < rsi < req_body.rsi_chop_max:
                    continue

                # MACD bullish vereist
                if macd_hist < 0:
                    continue

                position = {"entry": close, "ts": ts}
                open_positions += 1

        # Eventuele open positie sluiten
        if position and rows:
            last_close = float(rows[-1][5] or position["entry"])
            pnl = (last_close / position["entry"] - 1) * 100
            trades.append(round(pnl, 3))

        if not trades:
            continue

        wins = [p for p in trades if p > 0]
        losses = [abs(p) for p in trades if p <= 0]
        arr = np.array(trades)
        cumulative = np.cumsum(arr)
        peak = np.maximum.accumulate(cumulative)
        drawdown = float(np.max(peak - cumulative)) if len(cumulative) > 0 else 0.0

        per_coin[sym] = {
            "trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "total_pnl": round(float(sum(trades)), 2),
            "avg_pnl": round(float(np.mean(arr)), 3),
            "max_drawdown": round(drawdown, 2),
            "profit_factor": round(sum(wins) / sum(losses), 3) if losses and sum(losses) > 0 else 999.0,
        }
        all_trades.extend(trades)

    conn.close()

    if not all_trades:
        return {"error": "Geen trades gegenereerd — onvoldoende data of te strenge filters",
                "symbols": req_body.symbols, "strategy": req_body.dict()}

    arr_all = np.array(all_trades)
    wins_all = [p for p in all_trades if p > 0]
    losses_all = [abs(p) for p in all_trades if p <= 0]
    cum_all = np.cumsum(arr_all)
    peak_all = np.maximum.accumulate(cum_all)
    dd_all = float(np.max(peak_all - cum_all)) if len(cum_all) > 0 else 0.0

    return {
        "strategy": {
            "btc_filter": req_body.btc_filter,
            "rsi_buy_threshold": req_body.rsi_buy_threshold,
            "rsi_chop_max": req_body.rsi_chop_max,
            "rsi_sell_threshold": req_body.rsi_sell_threshold,
            "stoploss_pct": req_body.stoploss_pct,
            "takeprofit_pct": req_body.takeprofit_pct,
            "max_positions": req_body.max_positions,
        },
        "totaal": {
            "trades": len(all_trades),
            "win_rate": round(len(wins_all) / len(all_trades) * 100, 1),
            "total_pnl": round(float(sum(all_trades)), 2),
            "avg_pnl_per_trade": round(float(np.mean(arr_all)), 3),
            "max_drawdown": round(dd_all, 2),
            "profit_factor": round(sum(wins_all) / sum(losses_all), 3) if losses_all and sum(losses_all) > 0 else 999.0,
        },
        "per_coin": per_coin,
    }


@app.get("/top-coins")
def top_coins(limit: int = 50):
    """Haal top coins op van Binance op basis van 24h USDT volume."""
    try:
        r = req.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=15)
        r.raise_for_status()
        tickers = r.json()
        usdt_pairs = [
            t for t in tickers
            if t["symbol"].endswith("USDT")
            and not any(s in t["symbol"] for s in ["UP", "DOWN", "BULL", "BEAR"])
            and float(t["quoteVolume"]) > 1_000_000
        ]
        usdt_pairs.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [
            {"symbol": t["symbol"], "volume_usdt": round(float(t["quoteVolume"]), 0),
             "price_change_pct": round(float(t["priceChangePercent"]), 2)}
            for t in usdt_pairs[:limit]
        ]
    except Exception as e:
        raise HTTPException(502, f"Binance fout: {e}")


@app.get("/indicators/{symbol}")
def get_indicators(symbol: str, interval: str = "1h", limit: int = 1):
    """Haal meest recente indicators op voor een coin."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(adapt_query("""
        SELECT i.ts, i.rsi, i.macd_hist, i.bb_width, i.bb_position, i.ema21, i.ema55,
               i.ema_bull, i.adx, i.stoch_rsi_k, i.atr, i.volume_ratio, i.rsi_zone,
               i.ema200, o.close
        FROM indicators_data i
        LEFT JOIN ohlcv_data o ON o.symbol=i.symbol AND o.interval=i.interval AND o.ts=i.ts
        WHERE i.symbol=? AND i.interval=?
        ORDER BY i.ts DESC
        LIMIT ?
    """), (symbol, interval, limit))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        raise HTTPException(404, f"Geen indicators voor {symbol} {interval}")
    result = []
    for r in rows:
        result.append({
            "ts": str(r[0]), "rsi": float(r[1] or 0), "macd_hist": float(r[2] or 0),
            "bb_width": float(r[3] or 0), "bb_position": r[4], "ema21": float(r[5] or 0),
            "ema55": float(r[6] or 0), "ema_bull": r[7], "adx": float(r[8] or 0),
            "stoch_rsi_k": float(r[9] or 0), "atr": float(r[10] or 0),
            "volume_ratio": float(r[11] or 0), "rsi_zone": r[12],
            "ema200": float(r[13]) if r[13] else None,
            "close": float(r[14]) if r[14] else None,
        })
    return result[0] if limit == 1 else result


@app.get("/signal/{symbol}")
def get_signal(symbol: str, interval: str = "1h"):
    """Geeft een onderbouwde signaal-aanbeveling op basis van pattern matching."""
    # Huidige indicators ophalen
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(adapt_query("""
        SELECT rsi, macd_hist, bb_position, ema_bull, adx, rsi_zone, ts
        FROM indicators_data
        WHERE symbol=? AND interval=?
        ORDER BY ts DESC LIMIT 1
    """), (symbol, interval))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, f"Geen indicator data voor {symbol} — run /import eerst")

    rsi, macd_hist, bb_pos, ema_bull, adx, rsi_z, ts = row
    rsi = float(rsi or 50)
    macd_hist = float(macd_hist or 0)
    adx = float(adx or 0)

    macd_dir  = "bullish" if macd_hist > 0 else "bearish"
    ema_align = "bull" if ema_bull else "bear"
    adx_str   = "strong" if adx > 25 else "weak"

    # BTC trend ophalen
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(adapt_query("""
        SELECT ema_bull FROM indicators_data
        WHERE symbol='BTCUSDT' AND interval=?
        ORDER BY ts DESC LIMIT 1
    """), (interval,))
    btc_row = cur.fetchone()
    conn.close()
    btc_trend = "bull" if (btc_row and btc_row[0]) else "bear"

    # Pattern lookup
    pattern = lookup_pattern(symbol, rsi_z or "neutral_low", macd_dir,
                             bb_pos or "lower_half", ema_align, btc_trend)

    # Signaal bepalen
    if not pattern["found"]:
        signaal = "HOLD"
        reden = f"Onvoldoende precedenten ({pattern['precedenten']})"
        confidence = 0.0
    elif pattern["avg_pnl_1h"] > 0.5 and pattern["win_rate"] > 55:
        signaal = "BUY"
        confidence = min(0.95, pattern["win_rate"] / 100)
        reden = (f"RSI {rsi_z}, {macd_dir} MACD, {ema_align} EMA — "
                 f"{pattern['precedenten']} precedenten, {pattern['win_rate']}% win rate")
    elif pattern["avg_pnl_1h"] < -0.4 or pattern["win_rate"] < 35:
        signaal = "AVOID"
        confidence = 0.0
        reden = f"Slechte historische PnL ({pattern['avg_pnl_1h']}%)"
    else:
        signaal = "HOLD"
        confidence = 0.3
        reden = f"Neutraal patroon ({pattern['win_rate']}% win rate)"

    return {
        "symbol":           symbol,
        "interval":         interval,
        "ts":               str(ts),
        "signaal":          signaal,
        "confidence":       round(confidence, 2),
        "precedenten":      pattern.get("precedenten", 0),
        "avg_pnl_1h":       pattern.get("avg_pnl_1h"),
        "avg_pnl_4h":       pattern.get("avg_pnl_4h"),
        "win_rate":         pattern.get("win_rate"),
        "worst_case_1h":    pattern.get("worst_1h"),
        "btc_trend":        btc_trend,
        "fingerprint": {
            "rsi_zone":      rsi_z,
            "macd_direction": macd_dir,
            "bb_position":   bb_pos,
            "ema_alignment": ema_align,
            "adx_strength":  adx_str,
        },
        "reden": reden,
    }


@app.get("/coverage")
def coverage():
    """Overzicht van beschikbare historische data per coin."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, interval, COUNT(*) as candles,
               MIN(ts) as first_ts, MAX(ts) as last_ts
        FROM ohlcv_data
        GROUP BY symbol, interval
        ORDER BY symbol, interval
    """)
    rows = cur.fetchall()
    conn.close()
    return [{"symbol": r[0], "interval": r[1], "candles": r[2],
             "first_ts": str(r[3]), "last_ts": str(r[4])} for r in rows]


@app.get("/patterns/{symbol}")
def pattern_stats(symbol: str, interval: str = "1h"):
    """Statistieken van opgeslagen patronen voor een coin."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(adapt_query("""
        SELECT rsi_zone, macd_direction, COUNT(*) as n,
               AVG(pnl_1h) as avg_pnl, AVG(CASE WHEN was_win THEN 1.0 ELSE 0.0 END)*100 as wr
        FROM pattern_results
        WHERE symbol=? AND interval=?
        GROUP BY rsi_zone, macd_direction
        ORDER BY avg_pnl DESC
    """), (symbol, interval))
    rows = cur.fetchall()
    conn.close()
    return [{"rsi_zone": r[0], "macd": r[1], "n": r[2],
             "avg_pnl_1h": round(float(r[3] or 0), 3),
             "win_rate": round(float(r[4] or 0), 1)} for r in rows]


class FeedbackRequest(BaseModel):
    symbol: str
    interval: str = "1h"
    pnl_1h: float
    pnl_4h: Optional[float] = None
    fingerprint: dict  # rsi_zone, macd_direction, bb_position, ema_alignment, adx_strength, btc_trend


@app.post("/feedback")
def trade_feedback(req_body: FeedbackRequest):
    """Sla het resultaat van een live trade op als nieuw patroon-datapunt."""
    fp = req_body.fingerprint
    ts = datetime.now(timezone.utc)
    was_win = req_body.pnl_1h > 0
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(adapt_query("""
            INSERT INTO pattern_results
            (symbol, ts, interval, rsi_zone, macd_direction, bb_position,
             ema_alignment, adx_strength, btc_trend, pnl_1h, pnl_4h, was_win)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """), (
            req_body.symbol, ts, req_body.interval,
            fp.get("rsi_zone"), fp.get("macd_direction"), fp.get("bb_position"),
            fp.get("ema_alignment"), fp.get("adx_strength"), fp.get("btc_trend"),
            req_body.pnl_1h, req_body.pnl_4h, was_win,
        ))
        conn.commit()
        log.info(f"[feedback] {req_body.symbol} {req_body.interval}: "
                 f"pnl_1h={req_body.pnl_1h:.3f}%, win={was_win}")
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()
    return {"ok": True, "symbol": req_body.symbol, "pnl_1h": req_body.pnl_1h, "was_win": was_win}


# ── Social / Market Sentiment Endpoints ──────────────────────────────────────

BINANCE_FUTURES = "https://fapi.binance.com"
_funding_cache: dict = {}   # symbol → {"rate": float, "ts": datetime}
_FUNDING_TTL = 300          # 5 minuten cache


@app.get("/funding/{symbol}")
def funding_rate(symbol: str):
    """Haal funding rate op van Binance Futures (gecached 5 min)."""
    sym = symbol.replace("-", "")
    now = datetime.now(timezone.utc)
    cached = _funding_cache.get(sym)
    if cached and (now - cached["ts"]).total_seconds() < _FUNDING_TTL:
        return cached

    try:
        r = req.get(f"{BINANCE_FUTURES}/fapi/v1/fundingRate",
                    params={"symbol": sym, "limit": 1}, timeout=5)
        r.raise_for_status()
        data = r.json()
        if not data:
            raise HTTPException(404, f"Geen funding data voor {sym}")
        rate = float(data[0]["fundingRate"])
        result = {
            "symbol": sym,
            "funding_rate": rate,
            "funding_rate_pct": round(rate * 100, 4),
            "sentiment": "long_heavy" if rate > 0.001 else ("short_heavy" if rate < -0.001 else "neutral"),
            "ts": str(now),
        }
        _funding_cache[sym] = {**result, "ts": now}
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Funding rate fout: {e}")


@app.get("/funding")
def funding_all():
    """Funding rates voor alle SAFE_COINS (gecached)."""
    results = []
    for sym in SAFE_COINS:
        sym = sym.strip()
        if not sym:
            continue
        try:
            results.append(funding_rate(sym))
        except Exception:
            pass
    results.sort(key=lambda x: abs(x.get("funding_rate", 0)), reverse=True)
    return results


@app.get("/whales/{symbol}")
def whale_activity(symbol: str, interval: str = "1h", lookback: int = 24):
    """Detecteer whale activiteit op basis van volume spikes in historische data."""
    sym = symbol.replace("-", "")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(adapt_query("""
        SELECT ts, volume, close
        FROM ohlcv_data
        WHERE symbol=? AND interval=?
        ORDER BY ts DESC
        LIMIT ?
    """), (sym, interval, lookback * 2))
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 10:
        raise HTTPException(404, f"Onvoldoende data voor {sym}")

    vols = [float(r[1]) for r in rows]
    avg_vol = sum(vols) / len(vols)
    if avg_vol == 0:
        raise HTTPException(422, "Volume is 0")

    spikes = []
    for r in rows[:lookback]:
        vol = float(r[1])
        ratio = vol / avg_vol
        if ratio > 2.0:  # spike = meer dan 2x gemiddeld volume
            spikes.append({
                "ts": str(r[0]),
                "volume": round(vol, 2),
                "volume_ratio": round(ratio, 2),
                "price": float(r[2]),
                "type": "extreme" if ratio > 4.0 else "significant",
            })

    return {
        "symbol": sym,
        "interval": interval,
        "lookback_candles": lookback,
        "avg_volume": round(avg_vol, 2),
        "spike_count": len(spikes),
        "whale_alert": len(spikes) >= 3,
        "spikes": spikes[:10],
    }


@app.get("/sentiment/{symbol}")
def market_sentiment(symbol: str):
    """Gecombineerde sentiment samenvatting: funding rate + whale activiteit + pattern."""
    sym = symbol.replace("-", "")
    result = {"symbol": sym}

    # Funding rate
    try:
        result["funding"] = funding_rate(sym)
    except Exception:
        result["funding"] = None

    # Whale activiteit
    try:
        result["whales"] = whale_activity(sym, "1h", 24)
    except Exception:
        result["whales"] = None

    # Pattern signaal
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(adapt_query("""
            SELECT rsi_zone, ema_bull FROM indicators_data
            WHERE symbol=? AND interval='1h'
            ORDER BY ts DESC LIMIT 1
        """), (sym,))
        row = cur.fetchone()
        conn.close()
        result["current"] = {
            "rsi_zone": row[0] if row else None,
            "ema_bull": row[1] if row else None,
        }
    except Exception:
        result["current"] = None

    # Overall score
    score = 0
    if result["funding"] and result["funding"].get("sentiment") == "short_heavy":
        score += 1  # Short squeeze kans
    if result["whales"] and result["whales"].get("whale_alert"):
        score += 1  # Whale activiteit
    if result["current"] and result["current"].get("rsi_zone") in ("oversold", "neutral_low"):
        score += 1  # Technisch laag
    if result["current"] and result["current"].get("ema_bull"):
        score += 1  # Trend bullish

    result["sentiment_score"] = score
    result["sentiment_label"] = ["bearish", "neutraal", "licht_bullish", "bullish", "sterk_bullish"][min(score, 4)]
    return result


# ── Sniper Bot ────────────────────────────────────────────────────────────────

import uuid, threading
from typing import Optional

_snipers: dict = {}   # id → sniper config
_sniper_lock = threading.Lock()

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID   = os.getenv("TG_CHAT_ID", "")


def _tg_send(msg: str):
    """Stuur bericht naar Telegram als token beschikbaar."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log.info(f"[sniper-tg] {msg}")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = json.dumps({"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        r = req.post(url, data=payload, headers={"Content-Type": "application/json"}, timeout=5)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"[sniper-tg] Fout: {e}")


def _get_current_indicators(symbol: str, interval: str = "1h") -> dict:
    """Haal meest recente indicators op uit DB."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(adapt_query("""
            SELECT i.rsi, i.macd_hist, i.ema_bull, i.adx, i.volume_ratio, i.rsi_zone, o.close
            FROM indicators_data i
            LEFT JOIN ohlcv_data o ON o.symbol=i.symbol AND o.interval=i.interval AND o.ts=i.ts
            WHERE i.symbol=? AND i.interval=?
            ORDER BY i.ts DESC LIMIT 1
        """), (symbol, interval))
        row = cur.fetchone()
        conn.close()
        if not row:
            return {}
        return {
            "rsi": float(row[0]) if row[0] else None,
            "macd_hist": float(row[1]) if row[1] else None,
            "ema_bull": row[2],
            "adx": float(row[3]) if row[3] else None,
            "volume_ratio": float(row[4]) if row[4] else None,
            "rsi_zone": row[5],
            "close": float(row[6]) if row[6] else None,
        }
    except Exception as e:
        log.warning(f"[sniper] indicators fout: {e}")
        return {}


def _get_live_price(symbol: str) -> Optional[float]:
    """Haal live prijs op via Binance REST."""
    try:
        r = req.get(f"{BINANCE_BASE}/api/v3/ticker/price",
                    params={"symbol": symbol}, timeout=5)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return None


def _check_sniper(sniper: dict) -> bool:
    """Evalueer sniper condities. Returns True als trigger afgaat."""
    sym    = sniper["symbol"]
    mode   = sniper["mode"]
    ind    = _get_current_indicators(sym, sniper.get("interval", "1h"))
    price  = _get_live_price(sym)
    rsi    = ind.get("rsi")
    macd   = ind.get("macd_hist")
    ema_b  = ind.get("ema_bull")
    vol_r  = ind.get("volume_ratio")
    if not ind or price is None:
        return False

    if mode == "dip":
        rsi_thr = sniper.get("rsi_threshold", 28)
        triggered = (rsi is not None and rsi < rsi_thr
                     and (macd is None or macd >= 0 or vol_r is not None and vol_r < 1.0))
        if triggered:
            _tg_send(
                f"🎯 <b>SNIPER TRIGGER: {sym} DIP</b>\n"
                f"RSI: {rsi:.1f} (drempel: {rsi_thr})\n"
                f"Prijs: ${price:,.4f}\n"
                f"MACD hist: {macd:.6f if macd else 'n/a'}\n"
                f"Vol ratio: {vol_r:.2f if vol_r else 'n/a'}\n"
                f"✅ Optimaal koopmoment — kies zelf je entry"
            )
        return triggered

    elif mode == "short":
        rsi_thr = sniper.get("rsi_threshold", 68)
        triggered = (rsi is not None and rsi > rsi_thr
                     and macd is not None and macd < 0)
        if triggered:
            _tg_send(
                f"🎯 <b>SNIPER TRIGGER: {sym} SHORT</b>\n"
                f"RSI: {rsi:.1f} (drempel: {rsi_thr})\n"
                f"MACD: {macd:.6f} (negatief momentum)\n"
                f"Prijs: ${price:,.4f}\n"
                f"⚠️ Potentieel short entry — wees voorzichtig"
            )
        return triggered

    elif mode == "breakout":
        rsi_thr_lo = sniper.get("rsi_min", 50)
        rsi_thr_hi = sniper.get("rsi_max", 65)
        min_vol    = sniper.get("min_volume_ratio", 2.0)
        triggered  = (rsi is not None and rsi_thr_lo <= rsi <= rsi_thr_hi
                      and vol_r is not None and vol_r >= min_vol
                      and ema_b is True)
        if triggered:
            _tg_send(
                f"🎯 <b>SNIPER TRIGGER: {sym} BREAKOUT</b>\n"
                f"RSI: {rsi:.1f} | Volume ratio: {vol_r:.2f}x\n"
                f"EMA bullish: {ema_b}\n"
                f"Prijs: ${price:,.4f}\n"
                f"🚀 Breakout condities bereikt"
            )
        return triggered

    elif mode == "niveau":
        target = sniper.get("target_price", 0)
        direction = sniper.get("direction", "any")
        triggered = False
        if direction == "dip" and price <= target:
            triggered = True
        elif direction == "pump" and price >= target:
            triggered = True
        elif direction == "any" and abs(price - target) / target < 0.005:
            triggered = True
        if triggered:
            _tg_send(
                f"🎯 <b>SNIPER TRIGGER: {sym} NIVEAU ${target:,.4f}</b>\n"
                f"Huidige prijs: ${price:,.4f}\n"
                f"RSI: {rsi:.1f if rsi else 'n/a'}\n"
                f"📍 Prijs heeft doelniveau bereikt"
            )
        return triggered

    return False


def _sniper_monitor_loop():
    """Achtergrond loop die actieve snipers elke 60 seconden checkt."""
    while True:
        time.sleep(60)
        with _sniper_lock:
            to_remove = []
            for sid, s in list(_snipers.items()):
                try:
                    # Check max wachttijd
                    max_wait = s.get("max_wait_hours", 24) * 3600
                    age = time.time() - s["created_at"]
                    if age > max_wait:
                        log.info(f"[sniper] {sid} {s['symbol']} verlopen na {max_wait/3600:.0f}u")
                        _tg_send(f"⏰ Sniper {s['symbol']} {s['mode'].upper()} verlopen (max wachttijd bereikt)")
                        to_remove.append(sid)
                        continue

                    if _check_sniper(s):
                        log.info(f"[sniper] TRIGGER {sid} {s['symbol']} {s['mode']}")
                        to_remove.append(sid)
                except Exception as e:
                    log.warning(f"[sniper] Fout bij check {sid}: {e}")
            for sid in to_remove:
                del _snipers[sid]


# Start sniper monitor loop in achtergrond
_sniper_thread = threading.Thread(target=_sniper_monitor_loop, daemon=True)
_sniper_thread.start()


class SniperRequest(BaseModel):
    symbol: str
    mode: str                    # dip | short | breakout | niveau
    interval: str = "1h"
    rsi_threshold: Optional[float] = None   # voor dip/short
    rsi_min: Optional[float] = None         # voor breakout
    rsi_max: Optional[float] = None         # voor breakout
    min_volume_ratio: Optional[float] = None
    target_price: Optional[float] = None    # voor niveau
    direction: Optional[str] = "any"        # voor niveau: dip | pump | any
    max_wait_hours: float = 24
    label: Optional[str] = None


@app.post("/sniper/set")
def sniper_set(req_body: SniperRequest):
    """Stel een nieuwe sniper in. Modes: dip, short, breakout, niveau."""
    sid = str(uuid.uuid4())[:8]
    sniper = req_body.dict()
    sniper["created_at"] = time.time()
    sniper["id"] = sid
    sniper["symbol"] = sniper["symbol"].replace("-", "").upper()

    # Defaults per mode
    if sniper["mode"] == "dip" and sniper.get("rsi_threshold") is None:
        sniper["rsi_threshold"] = 28.0
    if sniper["mode"] == "short" and sniper.get("rsi_threshold") is None:
        sniper["rsi_threshold"] = 68.0
    if sniper["mode"] == "breakout":
        sniper.setdefault("rsi_min", 50.0)
        sniper.setdefault("rsi_max", 65.0)
        sniper.setdefault("min_volume_ratio", 2.0)

    with _sniper_lock:
        _snipers[sid] = sniper

    log.info(f"[sniper] Nieuw: {sid} {sniper['symbol']} {sniper['mode']}")
    _tg_send(
        f"🎯 Sniper gezet: {sniper['symbol']} {sniper['mode'].upper()}\n"
        f"Max wachttijd: {sniper['max_wait_hours']}u\n"
        f"{'RSI drempel: ' + str(sniper.get('rsi_threshold','')) if sniper.get('rsi_threshold') else ''}"
        f"{'Niveau: $' + str(sniper.get('target_price','')) if sniper.get('target_price') else ''}"
    )
    return {"ok": True, "id": sid, "sniper": sniper}


@app.get("/sniper/list")
def sniper_list():
    """Toon alle actieve snipers met status."""
    with _sniper_lock:
        result = []
        for sid, s in _snipers.items():
            age_h = (time.time() - s["created_at"]) / 3600
            remaining_h = s.get("max_wait_hours", 24) - age_h
            ind = _get_current_indicators(s["symbol"], s.get("interval", "1h"))
            result.append({
                "id": sid,
                "symbol": s["symbol"],
                "mode": s["mode"],
                "label": s.get("label"),
                "rsi_threshold": s.get("rsi_threshold"),
                "target_price": s.get("target_price"),
                "current_rsi": ind.get("rsi"),
                "current_price": _get_live_price(s["symbol"]),
                "age_hours": round(age_h, 1),
                "remaining_hours": round(max(0, remaining_h), 1),
            })
        return result


@app.delete("/sniper/{sniper_id}")
def sniper_cancel(sniper_id: str):
    """Annuleer een actieve sniper."""
    with _sniper_lock:
        if sniper_id not in _snipers:
            raise HTTPException(404, f"Sniper {sniper_id} niet gevonden")
        s = _snipers.pop(sniper_id)
    log.info(f"[sniper] Geannuleerd: {sniper_id} {s['symbol']} {s['mode']}")
    _tg_send(f"❌ Sniper geannuleerd: {s['symbol']} {s['mode'].upper()}")
    return {"ok": True, "cancelled": sniper_id}


# ── Reverse Backtest ──────────────────────────────────────────────────────────

class ReverseBacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    crash_threshold_pct: float = -5.0   # negatief = daling
    pump_threshold_pct: Optional[float] = None   # positief = stijging
    lookback_hours: list = [1, 4, 8, 24]
    interval: str = "1h"


@app.post("/reverse-backtest")
def reverse_backtest(req_body: ReverseBacktestRequest):
    """
    Reverse backtest: identificeer crashes/pumps en analyseer welke signalen
    er van tevoren aanwezig waren. Bouwt een pre-crash fingerprint.
    """
    sym = req_body.symbol.replace("-", "").upper()
    interval = req_body.interval
    crash_thr = req_body.crash_threshold_pct / 100.0

    conn = get_conn()
    cur = conn.cursor()

    # Haal alle candles op gesorteerd op tijd
    cur.execute(adapt_query("""
        SELECT o.ts, o.close, i.rsi, i.macd_hist, i.ema_bull, i.volume_ratio, i.rsi_zone
        FROM ohlcv_data o
        LEFT JOIN indicators_data i ON i.symbol=o.symbol AND i.interval=o.interval AND i.ts=o.ts
        WHERE o.symbol=? AND o.interval=?
        ORDER BY o.ts ASC
    """), (sym, interval))
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 50:
        raise HTTPException(400, f"Onvoldoende data voor {sym} — run /import eerst")

    # Zoek crash events (close daalt X% t.o.v. N candles geleden)
    lookback_candles = max(req_body.lookback_hours)
    crash_events = []
    for i in range(lookback_candles, len(rows)):
        ts_now, close_now = rows[i][0], float(rows[i][1])
        close_then = float(rows[i - lookback_candles][1])
        if close_then > 0:
            pct_chg = (close_now - close_then) / close_then
            if pct_chg <= crash_thr:
                crash_events.append(i)

    if not crash_events:
        return {
            "symbol": sym, "crash_events_found": 0,
            "message": f"Geen crashes van {req_body.crash_threshold_pct}% gevonden in de data"
        }

    # Analyseer signalen VOOR elke crash
    signal_counts = {}
    for lb_h in req_body.lookback_hours:
        signal_counts[f"T-{lb_h}h"] = {
            "rsi_above_65": 0, "rsi_above_70": 0, "rsi_below_35": 0,
            "macd_negative": 0, "ema_bull_false": 0,
            "volume_spike": 0, "n": 0,
        }

    for crash_i in crash_events:
        for lb_h in req_body.lookback_hours:
            pre_i = crash_i - lb_h
            if pre_i < 0:
                continue
            _, _, rsi, macd, ema_bull, vol_r, rsi_zone = rows[pre_i]
            key = f"T-{lb_h}h"
            signal_counts[key]["n"] += 1
            if rsi:
                rsi = float(rsi)
                if rsi > 65: signal_counts[key]["rsi_above_65"] += 1
                if rsi > 70: signal_counts[key]["rsi_above_70"] += 1
                if rsi < 35: signal_counts[key]["rsi_below_35"] += 1
            if macd and float(macd) < 0:
                signal_counts[key]["macd_negative"] += 1
            if ema_bull is False or ema_bull == 0:
                signal_counts[key]["ema_bull_false"] += 1
            if vol_r and float(vol_r) > 1.5:
                signal_counts[key]["volume_spike"] += 1

    # Bereken frequenties
    pre_crash_signals = {}
    for key, counts in signal_counts.items():
        n = counts.pop("n", 1) or 1
        pre_crash_signals[key] = {
            sig: {"frequency": round(cnt / n, 2), "count": cnt}
            for sig, cnt in counts.items()
        }

    # Beste predictor
    best_predictor = None
    best_freq = 0.0
    for key, sigs in pre_crash_signals.items():
        for sig, data in sigs.items():
            if data["frequency"] > best_freq:
                best_freq = data["frequency"]
                best_predictor = f"{sig} op {key} ({data['frequency']*100:.0f}% van crashes)"

    # Combined fingerprint — signalen aanwezig in >50% van crashes
    fingerprint_signals = []
    for key, sigs in pre_crash_signals.items():
        for sig, data in sigs.items():
            if data["frequency"] >= 0.5:
                fingerprint_signals.append(f"{sig} ({key})")

    n_events = len(crash_events)
    return {
        "symbol": sym,
        "interval": interval,
        "crash_threshold_pct": req_body.crash_threshold_pct,
        "crash_events_found": n_events,
        "lookback_hours": req_body.lookback_hours,
        "pre_crash_signals": pre_crash_signals,
        "best_predictor": best_predictor,
        "combined_fingerprint": {
            "description": f"Signalen aanwezig in ≥50% van {n_events} crash events",
            "signals": fingerprint_signals,
            "crash_probability_if_3plus": "gebruik als vroeg-waarschuwing bij 3+ actieve signalen",
        }
    }


# ── Historical Context Enrichment ─────────────────────────────────────────────

HISTORICAL_CONTEXT_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_context (
    id          BIGSERIAL PRIMARY KEY,
    backtest_id INTEGER NOT NULL UNIQUE,
    symbol      TEXT NOT NULL,
    candle_ts   TIMESTAMPTZ NOT NULL,
    signal      TEXT NOT NULL,
    pnl_1h_pct  REAL,
    pnl_4h_pct  REAL,
    pnl_24h_pct REAL,
    rsi         REAL,
    rsi_zone    TEXT,
    macd_hist   REAL,
    bb_width    REAL,
    bb_position TEXT,
    ema21       REAL,
    ema55       REAL,
    ema200      REAL,
    ema_bull    INTEGER,
    adx         REAL,
    stoch_rsi_k REAL,
    stoch_rsi_d REAL,
    volume_ratio REAL,
    atr         REAL,
    btc_regime  TEXT,
    enriched_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hctx_symbol     ON historical_context(symbol);
CREATE INDEX IF NOT EXISTS idx_hctx_signal     ON historical_context(signal);
CREATE INDEX IF NOT EXISTS idx_hctx_rsi        ON historical_context(rsi);
CREATE INDEX IF NOT EXISTS idx_hctx_btcregime  ON historical_context(btc_regime);
"""

_enrich_running = False

def _run_historical_enrich():
    global _enrich_running
    if _enrich_running:
        log.info("[historical-enrich] Al bezig, sla over.")
        return
    _enrich_running = True
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Maak tabel aan (IF NOT EXISTS — wijzigt geen bestaande kolommen)
        for stmt in HISTORICAL_CONTEXT_SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        conn.commit()

        # Migraties: voeg ontbrekende kolommen toe (idempotent)
        cur.execute("""
            ALTER TABLE historical_context ADD COLUMN IF NOT EXISTS btc_regime TEXT
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_hctx_btcregime ON historical_context(btc_regime)
        """)
        conn.commit()

        # Vul via JOIN historical_backtest × indicators_data
        cur.execute("""
            INSERT INTO historical_context
                (backtest_id, symbol, candle_ts, signal,
                 pnl_1h_pct, pnl_4h_pct, pnl_24h_pct,
                 rsi, rsi_zone, macd_hist, bb_width, bb_position,
                 ema21, ema55, ema200, ema_bull,
                 adx, stoch_rsi_k, stoch_rsi_d, volume_ratio, atr)
            SELECT hb.id, hb.symbol, hb.candle_ts, hb.signal,
                   hb.pnl_1h_pct, hb.pnl_4h_pct, hb.pnl_24h_pct,
                   i.rsi, i.rsi_zone, i.macd_hist, i.bb_width, i.bb_position,
                   i.ema21, i.ema55, i.ema200, i.ema_bull::integer,
                   i.adx, i.stoch_rsi_k, i.stoch_rsi_d, i.volume_ratio, i.atr
            FROM historical_backtest hb
            JOIN indicators_data i
                ON i.symbol   = hb.symbol
               AND i.ts::timestamptz = hb.candle_ts::timestamptz
               AND i.interval = '1h'
            WHERE hb.pnl_1h_pct IS NOT NULL
            ON CONFLICT (backtest_id) DO NOTHING
        """)
        inserted = cur.rowcount
        conn.commit()

        # Vul btc_regime: bull als BTC ema_bull=true op zelfde candle_ts, anders bear
        cur.execute("""
            UPDATE historical_context hc
            SET btc_regime = CASE
                WHEN btc.ema_bull = true THEN 'bull'
                ELSE 'bear'
            END
            FROM indicators_data btc
            WHERE btc.symbol   = 'BTCUSDT'
              AND btc.interval = '1h'
              AND btc.ts::timestamptz = hc.candle_ts::timestamptz
              AND hc.btc_regime IS NULL
        """)
        regime_updated = cur.rowcount
        conn.commit()
        log.info(f"[historical-enrich] btc_regime gezet voor {regime_updated} rijen")

        cur.execute("SELECT COUNT(*) FROM historical_context")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM historical_backtest")
        backtest_total = cur.fetchone()[0]
        conn.close()
        log.info(f"[historical-enrich] Klaar: {inserted} nieuw, {total}/{backtest_total} totaal verrijkt")
    except Exception as e:
        log.error(f"[historical-enrich] Fout: {e}")
    finally:
        _enrich_running = False


@app.post("/historical-enrich")
def historical_enrich(background_tasks: BackgroundTasks):
    """Verrijkt historical_backtest met indicator-context via JOIN met indicators_data."""
    background_tasks.add_task(_run_historical_enrich)
    return {"status": "started", "message": "Historical enrichment gestart in achtergrond — check /historical-enrich/status"}


@app.get("/historical-enrich/status")
def historical_enrich_status():
    """Geeft de huidige stand van historical_context terug."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM historical_context")
        enriched = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM historical_backtest")
        total_bt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT symbol) FROM historical_context")
        coins = cur.fetchone()[0]
        cur.execute("SELECT MIN(candle_ts), MAX(candle_ts) FROM historical_context")
        mn, mx = cur.fetchone()
        conn.close()
        return {
            "enriched": enriched,
            "total_backtest": total_bt,
            "coverage_pct": round(enriched / total_bt * 100, 1) if total_bt else 0,
            "coins": coins,
            "date_range": {"from": str(mn), "to": str(mx)},
            "running": _enrich_running,
        }
    except Exception as e:
        return {"enriched": 0, "error": str(e)}


# ── Coin Auto-Discovery ────────────────────────────────────────────────────────

_known_coins: set = set()

def _check_new_coins():
    """Achtergrond job: detecteert nieuwe coins in signal_performance en importeert ze."""
    global _known_coins
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Coins die recent actief zijn in de trading engine
        cur.execute("""
            SELECT DISTINCT symbol FROM signal_performance
            WHERE ts > NOW() - INTERVAL '48 hours'
        """)
        active_coins = {r[0] for r in cur.fetchall()}

        # Coins die al data hebben in indicators_data
        cur.execute("SELECT DISTINCT symbol FROM indicators_data")
        covered_coins = {r[0] for r in cur.fetchall()}
        conn.close()

        new_coins = active_coins - covered_coins - _known_coins
        if new_coins:
            log.info(f"[coin-watcher] Nieuwe coins gedetecteerd: {new_coins}")
            for coin in new_coins:
                log.info(f"[coin-watcher] Import starten voor {coin}...")
                _import_symbol(coin, "1h", months=48)
                _known_coins.add(coin)
            # Na import: historical_context bijwerken
            _run_historical_enrich()
        else:
            # Update known set
            _known_coins = covered_coins
    except Exception as e:
        log.error(f"[coin-watcher] Fout: {e}")


@app.get("/coin-watcher/status")
def coin_watcher_status():
    """Geeft overzicht van gedekte en ontbrekende coins."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT symbol FROM signal_performance WHERE ts > NOW() - INTERVAL '48 hours'")
        active = sorted(r[0] for r in cur.fetchall())
        cur.execute("SELECT DISTINCT symbol FROM indicators_data")
        covered = sorted(r[0] for r in cur.fetchall())
        conn.close()
        missing = sorted(set(active) - set(covered))
        return {
            "active_coins": active,
            "covered_coins": covered,
            "missing_coverage": missing,
            "missing_count": len(missing),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Realtime WebSocket Feed ───────────────────────────────────────────────────

import websocket as _ws_lib  # websocket-client

_BINANCE_WS_URL = "wss://stream.binance.com:9443/stream"
_WS_CANDLE_IV   = "1m"
_WS_BUF_SIZE    = 300

_live_buffers: dict[str, deque] = {}       # symbol → deque of candle dicts
_live_buf_lock = threading.Lock()
_live_last_ts:  dict[str, float] = {}      # symbol → epoch float van laatste tick

_ws_state = {
    "connected":    False,
    "fallback_mode": False,
    "drops":        [],          # epoch floats van reconnects
    "running":      False,
}
_ws_instance = None


def _ws_drops_1h() -> int:
    cutoff = time.time() - 3600
    return sum(1 for t in _ws_state["drops"] if t > cutoff)


def _ws_on_message(ws, message):
    try:
        data  = json.loads(message)
        kline = data.get("data", {}).get("k", {})
        sym   = kline.get("s", "").upper()
        if sym and sym in _live_buffers:
            candle = {
                "ts":     int(kline["t"]),
                "open":   float(kline["o"]),
                "high":   float(kline["h"]),
                "low":    float(kline["l"]),
                "close":  float(kline["c"]),
                "volume": float(kline["v"]),
                "closed": bool(kline["x"]),
            }
            with _live_buf_lock:
                buf = _live_buffers[sym]
                if buf and buf[-1]["ts"] == candle["ts"]:
                    buf[-1] = candle
                else:
                    buf.append(candle)
                _live_last_ts[sym] = time.time()
    except Exception as e:
        log.warning(f"[ws] Parse fout: {e}")


def _ws_on_error(ws, err):
    log.warning(f"[ws] Fout: {err}")


def _ws_on_close(ws, code, msg):
    _ws_state["connected"] = False
    _ws_state["drops"].append(time.time())
    _ws_state["drops"] = _ws_state["drops"][-100:]
    log.warning(f"[ws] Verbinding verbroken (code={code})")


def _ws_on_open(ws):
    _ws_state["connected"] = True
    _ws_state["fallback_mode"] = False
    log.info(f"[ws] Verbonden — {len(_live_buffers)} symbols")


def _ws_seed_rest():
    """Vul buffers met REST data als baseline (ook bij WS-uitval)."""
    for sym in list(_live_buffers.keys()):
        try:
            rows = fetch_ohlcv(sym, _WS_CANDLE_IV, limit=_WS_BUF_SIZE)
            with _live_buf_lock:
                buf = _live_buffers[sym]
                buf.clear()
                for row in rows:
                    buf.append({
                        "ts": int(row[0]), "open": float(row[1]), "high": float(row[2]),
                        "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
                        "closed": True,
                    })
                _live_last_ts[sym] = time.time()
        except Exception as e:
            log.warning(f"[ws-seed] {sym}: {e}")


def _ws_run_loop():
    global _ws_instance
    symbols_lower = [s.lower() for s in _live_buffers.keys()]
    streams = "/".join(f"{s}@kline_{_WS_CANDLE_IV}" for s in symbols_lower)
    url = f"{_BINANCE_WS_URL}?streams={streams}"
    while _ws_state["running"]:
        try:
            _ws_instance = _ws_lib.WebSocketApp(
                url,
                on_message=_ws_on_message,
                on_error=_ws_on_error,
                on_close=_ws_on_close,
                on_open=_ws_on_open,
            )
            _ws_instance.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            log.warning(f"[ws] Connect fout: {e}")
        _ws_state["connected"] = False
        if _ws_state["running"]:
            time.sleep(5)
            log.info("[ws] Herverbinden...")
            _ws_seed_rest()


def _ws_fallback_loop():
    """Pollt REST als WS-lag > 60s of WS down is."""
    while _ws_state["running"]:
        time.sleep(30)
        if _ws_state["connected"]:
            lags = [time.time() - _live_last_ts.get(s, 0) for s in _live_buffers]
            if lags and max(lags) > 60:
                _ws_state["fallback_mode"] = True
                log.warning("[ws-fallback] Lag > 60s — REST fallback")
                _ws_seed_rest()
            elif _ws_state["fallback_mode"]:
                _ws_state["fallback_mode"] = False
        else:
            _ws_seed_rest()


def _start_ws_feed():
    for sym in SAFE_COINS:
        _live_buffers[sym.upper()] = deque(maxlen=_WS_BUF_SIZE)
        _live_last_ts[sym.upper()] = 0.0
    _ws_state["running"] = True
    _ws_seed_rest()
    threading.Thread(target=_ws_run_loop,      daemon=True, name="ws-feed").start()
    threading.Thread(target=_ws_fallback_loop, daemon=True, name="ws-fallback").start()
    log.info(f"[ws] Live feed gestart voor {len(_live_buffers)} symbols")


def _ws_stop():
    _ws_state["running"] = False
    if _ws_instance:
        try:
            _ws_instance.close()
        except Exception:
            pass


# ── Snapshot helper ───────────────────────────────────────────────────────────

def _compute_snapshot(symbol: str) -> dict:
    sym = symbol.upper()
    if sym not in _live_buffers:
        raise HTTPException(404, f"Symbol {sym} niet in live feed")

    with _live_buf_lock:
        buf = _live_buffers[sym]
        latest = dict(buf[-1]) if buf else None
    if not latest:
        raise HTTPException(503, f"Geen live data voor {sym} — feed seed bezig")

    lag_ms = round((time.time() - _live_last_ts.get(sym, 0)) * 1000, 0)
    price  = latest["close"]

    # Indicators uit DB (1h — meest recent)
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("""
        SELECT i.rsi, i.macd_hist, i.bb_width, i.bb_position,
               i.ema21, i.ema55, i.ema200, i.ema_bull,
               i.adx, i.stoch_rsi_k, i.atr, i.volume_ratio, i.rsi_zone
        FROM indicators_data i
        WHERE i.symbol=? AND i.interval='1h'
        ORDER BY i.ts DESC LIMIT 1
    """), (sym,))
    row = cur.fetchone()

    # BTC EMA200 + close voor regime
    cur.execute(adapt_query("""
        SELECT i.ema200, o.close
        FROM indicators_data i
        LEFT JOIN ohlcv_data o ON o.symbol=i.symbol AND o.interval=i.interval AND o.ts=i.ts
        WHERE i.symbol='BTCUSDT' AND i.interval='4h'
        ORDER BY i.ts DESC LIMIT 1
    """))
    btc_row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(503, f"Geen indicator data voor {sym} — wacht op update cycle")

    rsi, macd_hist, bb_width, bb_pos, ema21, ema55, ema200, ema_bull, adx, stoch_k, atr, vol_ratio, rsi_zone = row
    rsi       = float(rsi or 50)
    macd_hist = float(macd_hist or 0)
    bb_width  = float(bb_width or 0)
    adx       = float(adx or 0)
    atr       = float(atr or 0)
    ema21     = float(ema21 or price)
    ema55     = float(ema55 or price)
    ema200    = float(ema200 or price)
    stoch_k   = float(stoch_k or 50)
    vol_ratio = float(vol_ratio or 1.0)

    # BTC regime
    if btc_row and btc_row[0] and btc_row[1]:
        btc_ema200_val = float(btc_row[0])
        btc_close_val  = float(btc_row[1])
        btc_dist = (btc_close_val - btc_ema200_val) / btc_ema200_val * 100
        btc_regime = "bull" if btc_dist > 3 else ("bear" if btc_dist < -3 else "chop")
    else:
        btc_regime = "unknown"

    # ── trend_bot ─────────────────────────────────────────────────────────
    ema_dist_21  = (price - ema21)  / ema21  * 100 if ema21  else 0.0
    ema_dist_55  = (price - ema55)  / ema55  * 100 if ema55  else 0.0
    ema_dist_200 = (price - ema200) / ema200 * 100 if ema200 else 0.0

    trend_score   = 0.0
    trend_signals = []
    if ema_bull:
        trend_score += 0.4
        trend_signals.append("EMA21>EMA55>EMA200 (bull)")
    else:
        trend_score -= 0.4
        trend_signals.append("EMA alignment bearish")
    if btc_regime == "bull":
        trend_score += 0.3
        trend_signals.append("BTC regime bull")
    elif btc_regime == "bear":
        trend_score -= 0.3
        trend_signals.append("BTC regime bear")
    if adx > 25:
        trend_signals.append(f"ADX={adx:.1f} (trending)")

    # ── momentum_bot ──────────────────────────────────────────────────────
    momentum_score   = 0.0
    momentum_signals = []
    if rsi < 30:
        momentum_score += 0.5
        momentum_signals.append(f"RSI={rsi:.1f} oversold")
    elif rsi > 70:
        momentum_score -= 0.5
        momentum_signals.append(f"RSI={rsi:.1f} overbought")
    else:
        momentum_score += 0.15 if rsi < 45 else (-0.15 if rsi > 55 else 0.0)
    if macd_hist > 0:
        momentum_score += 0.3
        momentum_signals.append("MACD hist positief")
    else:
        momentum_score -= 0.3
        momentum_signals.append("MACD hist negatief")
    if stoch_k < 20:
        momentum_score += 0.2
        momentum_signals.append(f"StochRSI K={stoch_k:.1f} oversold")
    elif stoch_k > 80:
        momentum_score -= 0.2
        momentum_signals.append(f"StochRSI K={stoch_k:.1f} overbought")

    # ── volatility_bot ────────────────────────────────────────────────────
    bb_squeeze       = bb_width < 2.0
    vol_surge        = vol_ratio > 2.0
    volatility_signals = []
    if bb_squeeze:
        volatility_signals.append(f"BB squeeze (width={bb_width:.2f}%)")
    if vol_surge:
        volatility_signals.append(f"Volume surge ({vol_ratio:.1f}x)")
    if atr > 0:
        volatility_signals.append(f"ATR={atr:.4f}")

    # ── fusion ────────────────────────────────────────────────────────────
    fusion_score = trend_score * 0.4 + momentum_score * 0.4
    if bb_squeeze and vol_surge:
        fusion_score *= 1.2
    fusion_score = max(-1.0, min(1.0, fusion_score))
    confidence   = round(abs(fusion_score), 3)

    if fusion_score >= 0.35:
        action = "BUY"
    elif fusion_score <= -0.35:
        action = "SELL"
    elif confidence < 0.1:
        action = "HOLD"
    else:
        action = "WARN"

    top3 = (trend_signals + momentum_signals + volatility_signals)[:3]

    return {
        "symbol":     sym,
        "price":      price,
        "lag_ms":     lag_ms,
        "ts":         datetime.fromtimestamp(latest["ts"] / 1000, tz=timezone.utc).isoformat(),
        "btc_regime": btc_regime,
        "trend_bot": {
            "score":           round(trend_score, 3),
            "ema_bull":        bool(ema_bull),
            "ema_dist_21_pct": round(ema_dist_21, 2),
            "ema_dist_55_pct": round(ema_dist_55, 2),
            "ema_dist_200_pct":round(ema_dist_200, 2),
            "adx":             round(adx, 1),
            "signals":         trend_signals,
        },
        "momentum_bot": {
            "score":      round(momentum_score, 3),
            "rsi":        round(rsi, 1),
            "rsi_zone":   rsi_zone,
            "macd_hist":  round(macd_hist, 6),
            "stoch_rsi_k":round(stoch_k, 1),
            "signals":    momentum_signals,
        },
        "volatility_bot": {
            "bb_width":   round(bb_width, 2),
            "bb_position":bb_pos,
            "atr":        round(atr, 6),
            "volume_ratio":round(vol_ratio, 2),
            "bb_squeeze": bb_squeeze,
            "vol_surge":  vol_surge,
            "signals":    volatility_signals,
        },
        "fusion": {
            "action":     action,
            "score":      round(fusion_score, 3),
            "confidence": confidence,
            "explain":    top3,
        },
    }


# ── Realtime endpoints ────────────────────────────────────────────────────────

@app.get("/realtime/snapshot")
def realtime_snapshot(symbol: str = "BTCUSDT"):
    """Realtime snapshot: live prijs + trend/momentum/volatility scores + fusion output."""
    return _compute_snapshot(symbol)


@app.get("/realtime/health")
def realtime_health():
    """WS feed health: connectie, lag, drops, fallback status."""
    now = time.time()
    lags = {sym: round((now - ts) * 1000, 0)
            for sym, ts in _live_last_ts.items() if ts > 0}
    max_lag  = max(lags.values()) if lags else -1
    avg_lag  = round(sum(lags.values()) / len(lags), 0) if lags else -1
    worst    = max(lags, key=lags.get) if lags else None
    return {
        "ws_connected":      _ws_state["connected"],
        "fallback_mode":     _ws_state["fallback_mode"],
        "drops_1h":          _ws_drops_1h(),
        "max_lag_ms":        max_lag,
        "avg_lag_ms":        avg_lag,
        "worst_symbol":      worst,
        "symbols_tracking":  len(_live_buffers),
    }

# ── Alert Bot + Panic-Mode + Mode Orchestrator ───────────────────────────────

# Config
SPIKE_THRESHOLD_PCT  = float(os.getenv("SPIKE_THRESHOLD_PCT",  "0.8"))
SPIKE_MAJOR_PCT      = float(os.getenv("SPIKE_MAJOR_PCT",      "1.5"))
SPIKE_EXTREME_PCT    = float(os.getenv("SPIKE_EXTREME_PCT",    "3.0"))
VOLUME_SURGE_RATIO   = float(os.getenv("VOLUME_SURGE_RATIO",   "1.8"))
ALERT_COOLDOWN_SEC   = int(os.getenv("ALERT_COOLDOWN_SEC",     "300"))
PANIC_DURATION_SEC   = int(os.getenv("PANIC_DURATION_SEC",     "90"))

# ── Short Execution Engine — config ──────────────────────────────────────────

SHORT_POT_USDT        = float(os.getenv("SHORT_POT_USDT",        "1000"))
SHORT_RISK_PCT        = float(os.getenv("SHORT_RISK_PCT",        "1.5"))
SHORT_MAX_POSITIONS   = int(os.getenv("SHORT_MAX_POSITIONS",     "2"))
SHORT_MAX_DAY_DD_PCT  = float(os.getenv("SHORT_MAX_DAY_DD_PCT",  "6.0"))
SHORT_TRAIL_PCT       = float(os.getenv("SHORT_TRAIL_PCT",       "1.5"))
SHORT_HARD_STOP_PCT   = float(os.getenv("SHORT_HARD_STOP_PCT",   "1.2"))
SHORT_TIME_STOP_MIN   = int(os.getenv("SHORT_TIME_STOP_MIN",     "20"))
SHORT_COOLDOWN_SEC    = int(os.getenv("SHORT_COOLDOWN_SEC",      "120"))
SHORT_RE_ENTRY_SEC    = int(os.getenv("SHORT_RE_ENTRY_SEC",      "30"))
SHORT_MAX_SPREAD_BPS  = float(os.getenv("SHORT_MAX_SPREAD_BPS",  "12"))
SHORT_MAX_SLIP_BPS    = float(os.getenv("SHORT_MAX_SLIP_BPS",    "15"))
SHORT_MIN_DELTA_PCT   = float(os.getenv("SHORT_MIN_DELTA_PCT",   "-1.5"))

_short_state: dict = {
    "armed":            False,
    "enabled":          True,
    "block_reason":     None,
    "open_positions":   [],       # list of live position dicts
    "day_dd_pct":       0.0,
    "day_losses_usdt":  0.0,
    "day_date":         None,     # UTC date YYYY-MM-DD
    "last_entry_ts":    {},       # symbol → epoch
}
_short_lock           = threading.Lock()
_short_log_buf: deque = deque(maxlen=1000)


def _short_log(symbol: str, action: str, reason: str,
               price: float = 0.0, pnl_pct: float = None, details: dict = None):
    entry = {
        "ts":      datetime.now(timezone.utc).isoformat(),
        "symbol":  symbol, "action": action,
        "reason":  reason, "price":  price,
        "pnl_pct": round(pnl_pct, 3) if pnl_pct is not None else None,
        "details": details or {},
    }
    _short_log_buf.appendleft(entry)
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(adapt_query("""
            INSERT INTO short_log (symbol, action, reason, price, pnl_pct, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """), (symbol, action, reason, price,
               round(pnl_pct, 3) if pnl_pct is not None else None,
               json.dumps(details or {})))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"[short-log-db] {e}")


def _short_day_reset():
    """Reset dag-DD teller bij nieuwe UTC dag."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _short_state["day_date"] != today:
        with _short_lock:
            _short_state["day_date"]        = today
            _short_state["day_dd_pct"]      = 0.0
            _short_state["day_losses_usdt"] = 0.0
            if not _short_state["enabled"] and "dag DD" in (_short_state["block_reason"] or ""):
                _short_state["enabled"]     = True
                _short_state["block_reason"] = None
        log.info(f"[short] Dag reset — short weer enabled")


def _estimate_market_quality(sym: str) -> tuple[float, float]:
    """Schat spread_bps en slippage_bps uit WS candle data."""
    with _live_buf_lock:
        buf = _live_buffers.get(sym)
        candles = list(buf)[-3:] if buf and len(buf) >= 3 else []
    if not candles:
        return 999.0, 999.0
    last  = candles[-1]
    close = last["close"]
    if close <= 0:
        return 999.0, 999.0
    # Spread proxy: half of candle range as fraction of price (in bps)
    spread_bps   = (last["high"] - last["low"]) / close * 10000 / 2
    # Slippage proxy: avg body size of last 3 candles (volatility estimate)
    bodies = [abs(c["close"] - c["open"]) / c["close"] * 10000 for c in candles if c["close"] > 0]
    slip_bps = sum(bodies) / len(bodies) if bodies else 999.0
    return round(spread_bps, 2), round(slip_bps, 2)


def _short_open(sym: str, price: float, delta_pct: float, vol_ratio: float) -> bool:
    """Probeer een demo short te openen. Controleert alle entry-guards."""
    _short_day_reset()

    # Guard 1: mode
    if _mode["mode"] not in ("panic", "crash"):
        _short_log(sym, "reject", "mode niet panic/crash", price,
                   details={"mode": _mode["mode"]})
        return False

    # Guard 2: enabled + dag DD
    if not _short_state["enabled"]:
        _short_log(sym, "reject", _short_state["block_reason"] or "short disabled", price)
        return False

    # Guard 3: delta
    if delta_pct > SHORT_MIN_DELTA_PCT:
        _short_log(sym, "reject", f"delta {delta_pct:.2f}% > threshold {SHORT_MIN_DELTA_PCT}%",
                   price, details={"delta_pct": delta_pct})
        return False

    # Guard 4: volume surge
    if vol_ratio < VOLUME_SURGE_RATIO:
        _short_log(sym, "reject", f"vol_ratio {vol_ratio:.1f} < {VOLUME_SURGE_RATIO}",
                   price, details={"vol_ratio": vol_ratio})
        return False

    # Guard 5: max open positions
    if len(_short_state["open_positions"]) >= SHORT_MAX_POSITIONS:
        _short_log(sym, "reject", f"max posities ({SHORT_MAX_POSITIONS}) bereikt", price)
        return False

    # Guard 6: symbol cooldown
    now     = time.time()
    last_ts = _short_state["last_entry_ts"].get(sym, 0)
    elapsed = now - last_ts
    if elapsed < SHORT_COOLDOWN_SEC:
        _short_log(sym, "reject",
                   f"cooldown actief ({int(SHORT_COOLDOWN_SEC - elapsed)}s resterend)", price,
                   details={"cooldown_remaining_s": int(SHORT_COOLDOWN_SEC - elapsed)})
        return False

    # Guard 7: spread + slippage
    spread_bps, slip_bps = _estimate_market_quality(sym)
    if spread_bps > SHORT_MAX_SPREAD_BPS:
        _short_log(sym, "reject", f"spread {spread_bps:.1f}bps > {SHORT_MAX_SPREAD_BPS}bps",
                   price, details={"spread_bps": spread_bps})
        return False
    if slip_bps > SHORT_MAX_SLIP_BPS:
        _short_log(sym, "reject", f"slippage {slip_bps:.1f}bps > {SHORT_MAX_SLIP_BPS}bps",
                   price, details={"slip_bps": slip_bps})
        return False

    # Alle guards OK — open positie
    size_usdt    = SHORT_POT_USDT * (SHORT_RISK_PCT / 100)
    trail_stop   = round(price * (1 + SHORT_TRAIL_PCT / 100), 8)
    hard_stop    = round(price * (1 + SHORT_HARD_STOP_PCT / 100), 8)
    time_stop_ts = now + SHORT_TIME_STOP_MIN * 60

    # DB insert
    db_id = None
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(adapt_query("""
            INSERT INTO short_positions
            (symbol, entry_price, size_usdt, status,
             trigger_delta, trigger_vol_ratio, trigger_spread_bps, trigger_mode)
            VALUES (?, ?, ?, 'open', ?, ?, ?, ?)
        """), (sym, price, size_usdt, round(delta_pct, 3),
               round(vol_ratio, 2), round(spread_bps, 2), _mode["mode"]))
        conn.commit()
        cur.execute("SELECT lastval()")
        db_id = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        log.warning(f"[short-db] Insert fout: {e}")

    position = {
        "db_id":       db_id,
        "symbol":      sym,
        "entry_price": price,
        "entry_ts":    now,
        "size_usdt":   size_usdt,
        "trail_stop":  trail_stop,
        "hard_stop":   hard_stop,
        "time_stop_ts":time_stop_ts,
        "best_price":  price,   # laagst gezien (MFE voor short)
        "worst_price": price,   # hoogst gezien (MAE voor short)
    }
    with _short_lock:
        _short_state["open_positions"].append(position)
        _short_state["last_entry_ts"][sym] = now

    _short_log(sym, "entry", f"Short geopend @ {price}", price,
               details={"size_usdt": size_usdt, "trail_stop": trail_stop,
                        "hard_stop": hard_stop, "spread_bps": spread_bps,
                        "delta_pct": delta_pct, "vol_ratio": vol_ratio})
    _add_alert(sym, "short_signal", "major",
               f"Short OPEN @ {price} | size={size_usdt:.2f}USDT | trail={trail_stop}",
               price, delta_pct, vol_ratio)
    log.info(f"[short] Positie geopend {sym} @ {price}, size={size_usdt:.2f}USDT")
    return True


def _short_close(position: dict, price: float, reason: str):
    """Sluit een open short positie."""
    entry      = position["entry_price"]
    pnl_pct    = round((entry - price) / entry * 100, 3)
    duration_s = int(time.time() - position["entry_ts"])
    mae_pct    = round((position["worst_price"] - entry) / entry * 100, 3)
    mfe_pct    = round((entry - position["best_price"]) / entry * 100, 3)
    size_usdt  = position["size_usdt"]
    pnl_usdt   = round(size_usdt * pnl_pct / 100, 4)

    with _short_lock:
        if position in _short_state["open_positions"]:
            _short_state["open_positions"].remove(position)
        if pnl_pct < 0:
            _short_state["day_dd_pct"]      += abs(pnl_pct)
            _short_state["day_losses_usdt"] += abs(pnl_usdt)
            if _short_state["day_dd_pct"] >= SHORT_MAX_DAY_DD_PCT:
                _short_state["enabled"]     = False
                _short_state["block_reason"] = f"Dag DD {_short_state['day_dd_pct']:.1f}% >= {SHORT_MAX_DAY_DD_PCT}%"
                log.warning(f"[short] Dag DD limiet bereikt — short disabled tot UTC reset")

    # DB update
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(adapt_query("""
            UPDATE short_positions
            SET ts_exit=NOW(), exit_price=?, status='closed', exit_reason=?,
                pnl_pct=?, duration_s=?, mae_pct=?, mfe_pct=?
            WHERE id=?
        """), (price, reason, pnl_pct, duration_s, mae_pct, mfe_pct, position["db_id"]))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"[short-db] Update fout: {e}")

    _short_log(position["symbol"], "exit", reason, price, pnl_pct,
               details={"entry": entry, "duration_s": duration_s,
                        "mae_pct": mae_pct, "mfe_pct": mfe_pct, "pnl_usdt": pnl_usdt})
    _add_alert(position["symbol"], "short_signal",
               "major" if pnl_pct >= 0 else "minor",
               f"Short CLOSE @ {price} ({reason}) | PnL={pnl_pct:+.2f}% ({pnl_usdt:+.4f}USDT)",
               price, pnl_pct, 0)
    log.info(f"[short] Positie gesloten {position['symbol']} @ {price} | {reason} | PnL={pnl_pct:+.2f}%")


def _short_monitor_positions(current_prices: dict):
    """Controleer alle open shorts op exit condities."""
    now = time.time()
    for pos in list(_short_state["open_positions"]):
        sym   = pos["symbol"]
        price = current_prices.get(sym)
        if price is None:
            continue

        # MAE/MFE bijhouden
        if price > pos["worst_price"]:
            pos["worst_price"] = price
        if price < pos["best_price"]:
            pos["best_price"] = price
            # Trailing stop verlagen bij nieuwe low
            new_trail = round(price * (1 + SHORT_TRAIL_PCT / 100), 8)
            if new_trail < pos["trail_stop"]:
                pos["trail_stop"] = new_trail

        # Exit checks
        if price >= pos["hard_stop"]:
            _short_close(pos, price, f"Hard stoploss (price {price} >= {pos['hard_stop']})")
            continue
        if price >= pos["trail_stop"]:
            _short_close(pos, price, f"Trailing stop (price {price} >= {pos['trail_stop']})")
            continue
        if now >= pos["time_stop_ts"]:
            _short_close(pos, price, f"Time stop ({SHORT_TIME_STOP_MIN}min verlopen)")
            continue
        # Reversal exit: mode terug normal + momentum positief
        if _mode["mode"] == "normal":
            _short_close(pos, price, "Reversal exit (mode=normal)")
            continue


# Alert store (in-memory ring + DB persist)
_alerts: deque        = deque(maxlen=500)
_alert_lock           = threading.Lock()
_alert_cooldown: dict = {}   # symbol → last alert epoch

# Mode state machine
_mode: dict = {
    "mode":        "normal",  # normal | panic | crash
    "since":       None,
    "reason":      None,
    "armed_short": False,
    "short_entry": None,      # hypothetische short entry prijs
    "short_trail": None,      # trailing stop prijs
}
_mode_lock          = threading.Lock()
_mode_log: deque    = deque(maxlen=200)
_panic_confirm: int = 0


def _add_alert(symbol: str, kind: str, severity: str, msg: str,
               price: float, delta_pct: float, vol_ratio: float) -> dict:
    now  = time.time()
    last = _alert_cooldown.get(symbol, 0)
    if now - last < ALERT_COOLDOWN_SEC and severity != "extreme":
        return {}
    alert = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "kind": kind, "severity": severity,
        "message": msg, "price": price,
        "delta_pct": round(delta_pct, 3), "vol_ratio": round(vol_ratio, 2),
    }
    with _alert_lock:
        _alerts.appendleft(alert)
        _alert_cooldown[symbol] = now
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(adapt_query("""
            INSERT INTO alerts (symbol, kind, severity, message, price, delta_pct, vol_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """), (symbol, kind, severity, msg, price, round(delta_pct, 3), round(vol_ratio, 2)))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"[alert-db] {e}")
    log.info(f"[alert] {severity.upper()} {symbol} {kind}: {msg}")
    return alert


def _set_mode(new_mode: str, reason: str):
    global _panic_confirm
    with _mode_lock:
        old = _mode["mode"]
        if old == new_mode:
            return
        _mode.update({"mode": new_mode, "since": datetime.now(timezone.utc).isoformat(),
                      "reason": reason})
        if new_mode == "panic":
            _mode["armed_short"] = True
        elif new_mode == "normal":
            _mode.update({"armed_short": False, "short_entry": None, "short_trail": None})
        _panic_confirm = 0
    # Sync short_state armed flag
    with _short_lock:
        _short_state["armed"] = (new_mode in ("panic", "crash"))
        if new_mode == "normal":
            _short_state["armed"] = False

    _mode_log.appendleft({"ts": _mode["since"], "from": old, "to": new_mode, "reason": reason})
    log.info(f"[mode] {old} → {new_mode}: {reason}")
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(adapt_query("INSERT INTO mode_log (mode_from, mode_to, reason) VALUES (?,?,?)"),
                    (old, new_mode, reason))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"[mode-db] {e}")
    _add_alert("SYSTEM", "mode_switch", "extreme" if new_mode == "crash" else "major",
               f"Mode: {old} → {new_mode} — {reason}", 0, 0, 0)


def _check_short_entry(sym: str, price: float, delta_pct: float, vol_ratio: float):
    if not _mode["armed_short"] or _mode["short_entry"] is not None:
        return
    if delta_pct < -SPIKE_MAJOR_PCT and vol_ratio > VOLUME_SURGE_RATIO:
        trail = round(price * 1.015, 6)
        with _mode_lock:
            _mode["short_entry"] = price
            _mode["short_trail"] = trail
        _add_alert(sym, "short_signal", "major",
                   f"Short armed @ {price} | trail={trail} | Δ={delta_pct:.2f}%",
                   price, delta_pct, vol_ratio)


def _check_short_exit(sym: str, price: float):
    entry = _mode.get("short_entry")
    trail = _mode.get("short_trail")
    if not entry or not trail:
        return
    new_trail = price * 1.015
    if new_trail < trail:
        with _mode_lock:
            _mode["short_trail"] = new_trail
        return
    pnl = round((entry - price) / entry * 100, 3)
    _add_alert(sym, "short_signal", "major",
               f"Short EXIT @ {price} (trailing stop) | PnL={pnl:+.2f}%", price, pnl, 0)
    with _mode_lock:
        _mode["short_entry"] = None
        _mode["short_trail"] = None
    log.info(f"[short] Exit signal {sym} @ {price}, PnL={pnl:+.2f}%")


def _spike_monitor_loop():
    global _panic_confirm
    while True:
        time.sleep(5)
        try:
            with _live_buf_lock:
                snap = {sym: (list(buf)[-1], list(buf)[-2], list(buf)[-20:])
                        for sym, buf in _live_buffers.items() if len(buf) >= 3}
        except Exception:
            continue

        for sym, (latest, prev, last20) in snap.items():
            price      = latest["close"]
            prev_price = prev["close"]
            if prev_price <= 0:
                continue
            delta_pct = (price - prev_price) / prev_price * 100
            vol       = latest["volume"]
            avg_vol   = sum(c["volume"] for c in last20) / len(last20) if last20 else vol
            vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 1.0

            abs_d = abs(delta_pct)
            if abs_d < SPIKE_THRESHOLD_PCT:
                continue
            if abs_d >= SPIKE_EXTREME_PCT:
                severity = "extreme"
            elif abs_d >= SPIKE_MAJOR_PCT:
                severity = "major"
            else:
                severity = "minor"

            if severity == "minor" and vol_ratio < 1.5:
                continue

            kind = "spike" if delta_pct > 0 else "drop"
            _add_alert(sym, kind, severity,
                       f"{sym} {kind.upper()} {delta_pct:+.2f}%/60s @ {price} (vol {vol_ratio:.1f}x)",
                       price, delta_pct, vol_ratio)

            # Panic escalatie (extreme drops)
            if severity == "extreme" and delta_pct < 0:
                _panic_confirm += 1
                mode_now = _mode["mode"]
                if mode_now == "normal" and _panic_confirm >= 2:
                    _set_mode("panic", f"{sym} extreme drop {delta_pct:.2f}%")
                elif mode_now == "panic":
                    _set_mode("crash", f"{sym} extreme drop — escalatie")
            elif delta_pct > 0:
                _panic_confirm = max(0, _panic_confirm - 1)

            # Short execution: in panic/crash + short_signal condities
            if _mode["mode"] in ("panic", "crash") and _short_state["armed"]:
                _short_open(sym, price, delta_pct, vol_ratio)

        # Monitor open short positions
        current_prices = {}
        with _live_buf_lock:
            for sym, buf in _live_buffers.items():
                if buf:
                    current_prices[sym] = list(buf)[-1]["close"]
        _short_monitor_positions(current_prices)
        _short_day_reset()

        # Mode recovery check
        mode_now   = _mode["mode"]
        mode_since = _mode.get("since")
        if mode_now in ("panic", "crash") and mode_since:
            try:
                elapsed = (datetime.now(timezone.utc) -
                           datetime.fromisoformat(mode_since)).total_seconds()
                if elapsed > PANIC_DURATION_SEC and mode_now == "panic":
                    _set_mode("normal", f"Geen extreme events na {int(elapsed)}s")
                elif elapsed > PANIC_DURATION_SEC * 2 and mode_now == "crash":
                    _set_mode("normal", f"Crash voorbij na {int(elapsed)}s")
            except Exception:
                pass


# Patch _start_ws_feed om spike monitor mee te starten
_orig_start_ws_feed = _start_ws_feed


def _start_ws_feed():
    _orig_start_ws_feed()
    threading.Thread(target=_spike_monitor_loop, daemon=True, name="spike-monitor").start()
    log.info("[alert-bot] Spike monitor gestart")


# ── Alert + Mode endpoints ────────────────────────────────────────────────────

@app.get("/alerts/high-impact")
def alerts_high_impact(since: str = None, severity: str = None, limit: int = 50):
    """Kant-en-klare alert events: spikes, drops, short signals, mode switches."""
    with _alert_lock:
        items = list(_alerts)
    if severity:
        items = [a for a in items if a["severity"] == severity]
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            items = [a for a in items if datetime.fromisoformat(a["ts"]) >= since_dt]
        except Exception:
            pass
    return {"alerts": items[:limit], "total": len(items)}


@app.get("/mode/current")
def mode_current():
    """Huidig systeem-mode: normal | panic | crash. Apex_engine gebruikt dit voor no-new-buys."""
    return {
        "mode":              _mode["mode"],
        "since":             _mode["since"],
        "reason":            _mode["reason"],
        "armed_short":       _short_state["armed"],
        "short_enabled":     _short_state["enabled"],
        "short_block_reason":_short_state["block_reason"],
        "open_shorts":       len(_short_state["open_positions"]),
    }


@app.get("/short/status")
def short_status():
    """Short bot status: armed, enabled, open posities, dag DD, cooldowns."""
    now = time.time()
    cooldowns = {
        sym: round(max(0, SHORT_COOLDOWN_SEC - (now - ts)), 0)
        for sym, ts in _short_state["last_entry_ts"].items()
        if now - ts < SHORT_COOLDOWN_SEC
    }
    open_pos = []
    for p in _short_state["open_positions"]:
        entry   = p["entry_price"]
        # Get latest price from WS buffer
        with _live_buf_lock:
            buf = _live_buffers.get(p["symbol"])
            cur_price = list(buf)[-1]["close"] if buf else entry
        pnl_pct = round((entry - cur_price) / entry * 100, 3)
        open_pos.append({
            "symbol":       p["symbol"],
            "entry_price":  entry,
            "current_price":cur_price,
            "pnl_pct":      pnl_pct,
            "trail_stop":   p["trail_stop"],
            "hard_stop":    p["hard_stop"],
            "size_usdt":    p["size_usdt"],
            "time_stop_in_s":max(0, int(p["time_stop_ts"] - now)),
        })
    return {
        "armed":           _short_state["armed"],
        "enabled":         _short_state["enabled"],
        "block_reason":    _short_state["block_reason"],
        "open_positions":  open_pos,
        "open_count":      len(open_pos),
        "day_dd_pct":      round(_short_state["day_dd_pct"], 2),
        "day_losses_usdt": round(_short_state["day_losses_usdt"], 4),
        "day_dd_limit":    SHORT_MAX_DAY_DD_PCT,
        "last_entry":      _short_state["last_entry_ts"],
        "cooldowns_remaining": cooldowns,
        "config": {
            "pot_usdt":       SHORT_POT_USDT,
            "risk_pct":       SHORT_RISK_PCT,
            "max_positions":  SHORT_MAX_POSITIONS,
            "trail_pct":      SHORT_TRAIL_PCT,
            "hard_stop_pct":  SHORT_HARD_STOP_PCT,
            "time_stop_min":  SHORT_TIME_STOP_MIN,
            "cooldown_sec":   SHORT_COOLDOWN_SEC,
        },
    }


@app.get("/short/log")
def short_log_endpoint(since: str = None, limit: int = 100):
    """Log van alle short acties: entry, exit, reject."""
    items = list(_short_log_buf)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            items = [e for e in items if datetime.fromisoformat(e["ts"]) >= since_dt]
        except Exception:
            pass
    return {"log": items[:limit], "total": len(items)}


@app.get("/mode/log")
def mode_log_endpoint(limit: int = 50):
    """Geschiedenis van mode switches met reden en tijdstip."""
    return {"log": list(_mode_log)[:limit]}


# ── Fase 2: Level Replay ──────────────────────────────────────────────────────

@app.get("/replay/level")
def replay_level(
    symbol: str,
    level: float,
    tolerance_pct: float = 0.25,
    window_hours: int = 4,
):
    """
    Historische level-replay: hoe reageerde de prijs elke keer dat dit niveau
    werd aangetikt?

    Gebruikt ohlcv_data (1h candles). Returns 1h en 4h na elke touch.
    window_hours bepaalt max candles voor/na die getoond worden in closest_matches.
    """
    sym = symbol.upper()
    lo  = level * (1 - tolerance_pct / 100)
    hi  = level * (1 + tolerance_pct / 100)

    conn = get_conn()
    cur  = conn.cursor()

    # Haal alle 1h candles op voor dit symbol, gesorteerd op tijd
    cur.execute(adapt_query("""
        SELECT ts, open, high, low, close
        FROM ohlcv_data
        WHERE symbol=? AND interval='1h'
        ORDER BY ts ASC
    """), (sym,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        raise HTTPException(404, f"Geen OHLCV data voor {sym}")

    # Bouw ts→close map voor future price lookup
    ts_list    = [r[0] for r in rows]
    close_map  = {r[0]: float(r[4]) for r in rows}
    ts_indexed = {ts: i for i, ts in enumerate(ts_list)}

    def future_close(idx: int, hours: int) -> float | None:
        target_idx = idx + hours  # 1h candles → +1 idx = +1h
        if target_idx < len(ts_list):
            return close_map[ts_list[target_idx]]
        return None

    # Vind candles waarbij low ≤ level ≤ high (level aangetikt) OF close binnen tolerantie
    matches = []
    for i, row in enumerate(rows):
        ts, o, h, l, c = row
        o, h, l, c = float(o), float(h), float(l), float(c)
        touched = (l <= hi and h >= lo)  # candle raakt het level aan
        if not touched:
            continue

        p1h = future_close(i, 1)
        p4h = future_close(i, 4)
        if p1h is None:
            continue

        ret_1h = round((p1h / c - 1) * 100, 3)
        ret_4h = round((p4h / c - 1) * 100, 3) if p4h else None
        matches.append({
            "ts":      ts.isoformat(),
            "close":   round(c, 6),
            "ret_1h":  ret_1h,
            "ret_4h":  ret_4h,
            "win_1h":  ret_1h > 0,
            "win_4h":  ret_4h > 0 if ret_4h is not None else None,
            "dist_pct":round((c - level) / level * 100, 3),
        })

    if not matches:
        return {
            "symbol": sym, "level": level, "tolerance_pct": tolerance_pct,
            "matches_count": 0,
            "message": "Geen historische touches op dit niveau gevonden",
        }

    n         = len(matches)
    rets_1h   = [m["ret_1h"] for m in matches]
    rets_4h   = [m["ret_4h"] for m in matches if m["ret_4h"] is not None]
    wins_1h   = sum(1 for m in matches if m["win_1h"])
    wins_4h   = sum(1 for m in matches if m["win_4h"])
    n_4h      = len(rets_4h)

    # Confidence: gebaseerd op n en consistentie van 1h winrate
    wr_1h     = wins_1h / n
    confidence = min(1.0, round((n / 30) * 0.5 + abs(wr_1h - 0.5) * 2 * 0.5, 3))

    # Closest matches: max 5, gesorteerd op |dist_pct|
    closest = sorted(matches, key=lambda m: abs(m["dist_pct"]))[:5]

    return {
        "symbol":           sym,
        "level":            level,
        "tolerance_pct":    tolerance_pct,
        "matches_count":    n,
        "avg_return_1h":    round(sum(rets_1h) / n, 3),
        "avg_return_4h":    round(sum(rets_4h) / n_4h, 3) if n_4h else None,
        "winrate_1h":       round(wr_1h * 100, 1),
        "winrate_4h":       round(wins_4h / n_4h * 100, 1) if n_4h else None,
        "confidence":       confidence,
        "closest_matches":  closest,
    }


# ── Fase 2: Pattern Compare ───────────────────────────────────────────────────

class PatternCompareRequest(BaseModel):
    symbol: str
    interval: str = "1h"
    cross_symbol: bool = False   # ook andere coins gebruiken


@app.post("/pattern/compare")
def pattern_compare(req: PatternCompareRequest):
    """
    Vergelijk huidig patroon met historische precedenten uit pattern_results.

    Clustert op: rsi_zone, macd_direction, ema_alignment, btc_trend, adx_strength.
    Geeft top 3 clusters + historische uitkomsten + action suggestion.
    """
    sym = req.symbol.upper()

    # Haal huidige indicators op
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("""
        SELECT rsi_zone, macd_hist, ema_bull, adx, bb_position, rsi, ts
        FROM indicators_data
        WHERE symbol=? AND interval=?
        ORDER BY ts DESC LIMIT 1
    """), (sym, req.interval))
    row = cur.fetchone()

    # BTC trend voor context
    cur.execute(adapt_query("""
        SELECT ema_bull FROM indicators_data
        WHERE symbol='BTCUSDT' AND interval=?
        ORDER BY ts DESC LIMIT 1
    """), (req.interval,))
    btc_row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, f"Geen indicator data voor {sym} {req.interval}")

    rsi_zone, macd_hist, ema_bull, adx, bb_pos, rsi, ts = row
    macd_hist = float(macd_hist or 0)
    adx       = float(adx or 0)
    rsi       = float(rsi or 50)

    cur_macd_dir  = "bullish" if macd_hist > 0 else "bearish"
    cur_ema_align = "bull" if ema_bull else "bear"
    cur_adx_str   = "strong" if adx > 25 else "weak"
    cur_btc_trend = "bull" if (btc_row and btc_row[0]) else "bear"
    cur_rsi_zone  = rsi_zone or "neutral_low"

    current_pattern = {
        "rsi_zone":      cur_rsi_zone,
        "macd_direction":cur_macd_dir,
        "ema_alignment": cur_ema_align,
        "adx_strength":  cur_adx_str,
        "btc_trend":     cur_btc_trend,
        "rsi":           round(rsi, 1),
        "ts":            ts.isoformat() if ts else None,
    }

    # Query pattern_results — exact match eerst, dan versoepeld
    conn = get_conn()
    cur  = conn.cursor()

    sym_filter = "" if req.cross_symbol else "AND symbol=?"
    sym_params = () if req.cross_symbol else (sym,)

    # Cluster 1: exact (alle 5 dimensies)
    cur.execute(adapt_query(f"""
        SELECT symbol, rsi_zone, macd_direction, ema_alignment, adx_strength, btc_trend,
               COUNT(*) as n,
               AVG(pnl_1h) as avg_1h,
               AVG(pnl_4h) as avg_4h,
               AVG(CASE WHEN was_win THEN 1.0 ELSE 0.0 END) * 100 as winrate,
               MIN(pnl_1h) as worst_1h,
               MAX(pnl_1h) as best_1h
        FROM pattern_results
        WHERE rsi_zone=? AND macd_direction=? AND ema_alignment=?
          AND adx_strength=? AND btc_trend=?
          {sym_filter}
        GROUP BY symbol, rsi_zone, macd_direction, ema_alignment, adx_strength, btc_trend
        ORDER BY n DESC
        LIMIT 5
    """), (cur_rsi_zone, cur_macd_dir, cur_ema_align, cur_adx_str, cur_btc_trend) + sym_params)
    exact_rows = cur.fetchall()

    # Cluster 2: versoepeld — zelfde rsi_zone + ema_alignment + btc_trend (zonder adx/macd)
    cur.execute(adapt_query(f"""
        SELECT rsi_zone, ema_alignment, btc_trend,
               COUNT(*) as n,
               AVG(pnl_1h) as avg_1h,
               AVG(pnl_4h) as avg_4h,
               AVG(CASE WHEN was_win THEN 1.0 ELSE 0.0 END) * 100 as winrate
        FROM pattern_results
        WHERE rsi_zone=? AND ema_alignment=? AND btc_trend=?
          {sym_filter}
        GROUP BY rsi_zone, ema_alignment, btc_trend
        ORDER BY n DESC
        LIMIT 1
    """), (cur_rsi_zone, cur_ema_align, cur_btc_trend) + sym_params)
    broad_row = cur.fetchone()
    conn.close()

    def _fmt_cluster(row, kind: str) -> dict:
        if kind == "exact":
            sym_c, rz, md, ea, ads, bt, n, a1, a4, wr, w1, b1 = row
            label = f"{sym_c} {rz}+{md}+{ea}+{ads}+{bt}"
        else:
            rz, ea, bt, n, a1, a4, wr = row
            sym_c, ads, md, w1, b1 = sym, "?", "?", None, None
            label = f"{sym_c} {rz}+{ea}+{bt} (breed)"
        n = int(n or 0)
        return {
            "label":        label,
            "kind":         kind,
            "precedents":   n,
            "avg_pnl_1h":  round(float(a1 or 0), 3),
            "avg_pnl_4h":  round(float(a4 or 0), 3) if a4 else None,
            "winrate_1h":  round(float(wr or 0), 1),
            "worst_1h":    round(float(w1 or 0), 3) if w1 is not None else None,
            "best_1h":     round(float(b1 or 0), 3) if b1 is not None else None,
        }

    clusters = []
    for row in exact_rows:
        clusters.append(_fmt_cluster(row, "exact"))
    if broad_row:
        clusters.append(_fmt_cluster(broad_row, "broad"))

    # Action suggestion: gebaseerd op best cluster met genoeg precedenten
    action = "INSUFFICIENT_DATA"
    action_reason = "Onvoldoende precedenten"
    best = next((c for c in clusters if c["precedents"] >= 10), None)
    if best:
        wr = best["winrate_1h"]
        avg = best["avg_pnl_1h"]
        if wr >= 55 and avg > 0:
            action = "BUY"
            action_reason = f"Winrate {wr:.1f}% met avg +{avg:.2f}% in {best['precedents']} gevallen"
        elif wr <= 40 and avg < 0:
            action = "AVOID"
            action_reason = f"Lage winrate {wr:.1f}%, avg {avg:.2f}% in {best['precedents']} gevallen"
        else:
            action = "NEUTRAL"
            action_reason = f"Gemengd beeld: winrate {wr:.1f}%, avg {avg:.2f}%"

    # Afwijkingen t.o.v. meest voorkomende patroon in deze symbol
    deviations = []
    if cur_btc_trend == "bear" and cur_ema_align == "bull":
        deviations.append("EMA bull maar BTC bear — conflicterend")
    if cur_rsi_zone == "oversold" and cur_macd_dir == "bearish":
        deviations.append("RSI oversold maar MACD nog bearish — mogelijk vroeg")
    if cur_adx_str == "strong" and cur_btc_trend == "bear":
        deviations.append("Sterke trend (ADX) in bear-regime — verhoogd risico")

    return {
        "symbol":          sym,
        "interval":        req.interval,
        "current_pattern": current_pattern,
        "clusters":        clusters,
        "action":          action,
        "action_reason":   action_reason,
        "deviations":      deviations,
        "cross_symbol":    req.cross_symbol,
    }
