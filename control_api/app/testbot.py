"""
OpenClaw TestBot — paper trading bot voor STERK setups
Draait als background thread in control_api.

- Koopt alleen STERK setups (score >= 70, winrate >= 55%, avg_pnl >= 0.2%)
- Vaste inzet: $100 per trade
- Max 3 open trades tegelijk
- Sluit automatisch via TP (4.5%), SL (2.0%) of na 2 uur (TIMEOUT)
- Fees: 0.1% per kant (0.2% round trip) altijd meegerekend
- Alle trades gelogd in PostgreSQL: testbot_trades
"""

import os, json, sqlite3, threading, time, logging, requests
from datetime import datetime, timezone, timedelta
from db_compat import get_conn, adapt_query

log = logging.getLogger("testbot")

DB_PATH      = "/var/apex/apex.db"
BINANCE_URL  = "https://api.binance.com/api/v3/ticker/price"
_ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://jojo_analytics:8097")

# ── Configuratie ──────────────────────────────────────────────────────────────
STAKE_USD    = 100.0
MAX_TRADES   = 3
TP_PCT       = 4.5
SL_PCT       = 2.0
MAX_HOURS    = 2.0
FEE_PCT      = 0.1      # per kant, 0.2% round-trip
MONITOR_SEC  = 30       # hoe vaak open posities checken
SIGNAL_SEC   = 300      # hoe vaak op nieuwe signalen scannen

# Zelfde drempels als setup_judge.py (P1)
_SJ_STERK_WIN   = 55.0
_SJ_STERK_PNL   = 0.20
_SJ_MIN_N_STERK = 20
_SJ_SCORE_STERK = 70
_SJ_SCORE_TOE   = 50
_SJ_SCORE_ZWAK  = 30

# ── Bot state ─────────────────────────────────────────────────────────────────
_bot = {"running": False, "thread": None}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _binance_price(symbol: str) -> float | None:
    try:
        r = requests.get(BINANCE_URL, params={"symbol": symbol}, timeout=5)
        if r.ok:
            return float(r.json()["price"])
    except Exception:
        pass
    return None


def _sj_query(sql: str) -> list:
    try:
        r = requests.post(f"{_ANALYTICS_URL}/query", json={"sql": sql}, timeout=15)
        if r.ok:
            d = r.json()
            return d.get("rows") or d.get("data") or []
    except Exception as e:
        log.warning(f"testbot sj_query: {e}")
    return []


def _compute_score(win_pct, avg_pnl, n) -> tuple[int, str]:
    """Zelfde scoringlogica als setup_judge.py"""
    if win_pct is None or avg_pnl is None or n is None or n < 10:
        return 0, "SKIP"
    score = 0
    # Winrate (max 40 pt)
    if   win_pct >= 65: score += 40
    elif win_pct >= 55: score += 30
    elif win_pct >= 50: score += 20
    elif win_pct >= 45: score += 10
    # Gem. P&L (max 35 pt)
    if   avg_pnl >= 0.5: score += 35
    elif avg_pnl >= 0.3: score += 28
    elif avg_pnl >= 0.2: score += 20
    elif avg_pnl >= 0.1: score += 12
    elif avg_pnl >= 0.0: score += 5
    # n historisch (max 25 pt)
    if   n >= 50: score += 25
    elif n >= 30: score += 18
    elif n >= 20: score += 12
    elif n >= 10: score += 6

    if score >= _SJ_SCORE_STERK and win_pct >= _SJ_STERK_WIN and avg_pnl >= _SJ_STERK_PNL and n >= _SJ_MIN_N_STERK:
        verdict = "STERK"
    elif score >= _SJ_SCORE_TOE:
        verdict = "TOESTAAN"
    elif score >= _SJ_SCORE_ZWAK:
        verdict = "TOESTAAN_ZWAK"
    else:
        verdict = "SKIP"

    return score, verdict


# ── Database ──────────────────────────────────────────────────────────────────

def ensure_table():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS testbot_trades (
            id          SERIAL PRIMARY KEY,
            symbol      TEXT NOT NULL,
            signal      TEXT,
            setup_score INTEGER,
            entry_price NUMERIC(20,8) NOT NULL,
            entry_ts    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            stake_usd   NUMERIC(10,2) DEFAULT 100.0,
            tp_pct      NUMERIC(6,3)  DEFAULT 4.5,
            sl_pct      NUMERIC(6,3)  DEFAULT 2.0,
            tp_price    NUMERIC(20,8),
            sl_price    NUMERIC(20,8),
            price_15m   NUMERIC(20,8),
            price_1h    NUMERIC(20,8),
            price_2h    NUMERIC(20,8),
            close_price NUMERIC(20,8),
            close_ts    TIMESTAMPTZ,
            close_reason TEXT,
            pnl_pct     NUMERIC(10,4),
            pnl_usd     NUMERIC(10,4),
            fee_usd     NUMERIC(10,4),
            net_pnl_usd NUMERIC(10,4),
            status      TEXT NOT NULL DEFAULT 'open'
        )
    """)
    conn.commit()
    conn.close()


def _log_event(title: str, payload: dict):
    """Schrijf een testbot-event naar de events tabel in PostgreSQL."""
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(adapt_query("""
            INSERT INTO events (source, level, title, payload_json)
            VALUES (?,?,?,?)
        """), ("testbot", "INFO", title, json.dumps(payload)))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"[TestBot] event logging mislukt: {e}")


def _open_trade(symbol: str, signal: str, setup_score: int, entry_price: float):
    tp_price = round(entry_price * (1 + TP_PCT / 100), 8)
    sl_price = round(entry_price * (1 - SL_PCT / 100), 8)
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("""
        INSERT INTO testbot_trades
            (symbol, signal, setup_score, entry_price, stake_usd,
             tp_pct, sl_pct, tp_price, sl_price, status)
        VALUES (?,?,?,?,?,?,?,?,?,'open')
    """), (symbol, signal, setup_score, entry_price, STAKE_USD,
           TP_PCT, SL_PCT, tp_price, sl_price))
    conn.commit()
    conn.close()
    log.info(f"[TestBot] OPEN  {symbol} {signal} @ {entry_price:.4f}  TP={tp_price:.4f}  SL={sl_price:.4f}  score={setup_score}")
    _log_event(f"TestBot OPEN {symbol}", {
        "symbol": symbol, "signal": signal, "setup_score": setup_score,
        "entry_price": entry_price, "tp_price": tp_price, "sl_price": sl_price,
        "stake_usd": STAKE_USD,
    })


def _close_trade(trade_id: int, close_price: float, reason: str):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query(
        "SELECT entry_price, stake_usd FROM testbot_trades WHERE id=?"
    ), (trade_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return

    entry_price = float(row[0])
    stake_usd   = float(row[1])
    pnl_pct     = (close_price - entry_price) / entry_price * 100
    pnl_usd     = pnl_pct / 100 * stake_usd
    fee_usd     = stake_usd * FEE_PCT / 100 * 2   # entry + exit
    net_pnl_usd = pnl_usd - fee_usd

    cur.execute(adapt_query("""
        UPDATE testbot_trades SET
            close_price  = ?,
            close_ts     = NOW(),
            close_reason = ?,
            pnl_pct      = ?,
            pnl_usd      = ?,
            fee_usd      = ?,
            net_pnl_usd  = ?,
            status       = 'closed'
        WHERE id = ?
    """), (close_price, reason,
           round(pnl_pct, 4), round(pnl_usd, 4),
           round(fee_usd, 4), round(net_pnl_usd, 4),
           trade_id))
    conn.commit()
    conn.close()
    log.info(f"[TestBot] CLOSE #{trade_id} {reason} @ {close_price:.4f}  PnL={pnl_pct:+.3f}%  netto=${net_pnl_usd:+.2f}  fee=${fee_usd:.2f}")
    _log_event(f"TestBot CLOSE {reason} #{trade_id}", {
        "trade_id": trade_id, "close_reason": reason,
        "close_price": close_price, "pnl_pct": round(pnl_pct, 4),
        "pnl_usd": round(pnl_usd, 4), "fee_usd": round(fee_usd, 4),
        "net_pnl_usd": round(net_pnl_usd, 4),
    })


def _update_price_snapshot(trade_id: int, column: str, price: float):
    conn = get_conn()
    cur  = conn.cursor()
    # column is één van: price_15m, price_1h, price_2h — geen SQL-injectie risico
    # omdat we dit intern aanroepen met hardcoded strings
    cur.execute(adapt_query(
        f"UPDATE testbot_trades SET {column} = ? WHERE id = ? AND {column} IS NULL"
    ), (price, trade_id))
    conn.commit()
    conn.close()


# ── Bot loop ──────────────────────────────────────────────────────────────────

def _bot_loop():
    log.info("[TestBot] Loop gestart")
    ensure_table()
    last_signal_check = 0.0

    while _bot["running"]:
        now = time.time()

        # ── Monitor open posities ─────────────────────────────────────────
        try:
            conn = get_conn()
            cur  = conn.cursor()
            cur.execute(adapt_query("""
                SELECT id, symbol, entry_price, tp_price, sl_price, entry_ts
                FROM testbot_trades WHERE status='open'
            """))
            open_trades = cur.fetchall()
            conn.close()
        except Exception as e:
            log.warning(f"[TestBot] DB leesfout: {e}")
            time.sleep(MONITOR_SEC)
            continue

        n_open = len(open_trades)

        for row in open_trades:
            tid = row[0]
            sym = row[1]
            ep  = float(row[2])
            tp  = float(row[3])
            sl  = float(row[4])
            ets = row[5]

            # Parse entry_ts → datetime UTC
            if isinstance(ets, datetime):
                ets_dt = ets if ets.tzinfo else ets.replace(tzinfo=timezone.utc)
            else:
                try:
                    ets_dt = datetime.fromisoformat(str(ets).replace(" ", "T"))
                    if ets_dt.tzinfo is None:
                        ets_dt = ets_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    ets_dt = datetime.now(timezone.utc)

            age_h = (datetime.now(timezone.utc) - ets_dt).total_seconds() / 3600

            # Timeout check
            if age_h >= MAX_HOURS:
                price = _binance_price(sym) or ep
                _close_trade(tid, price, "TIMEOUT")
                n_open -= 1
                continue

            price = _binance_price(sym)
            if price is None:
                continue

            # Prijs-snapshots op vaste tijdpunten
            if age_h >= 0.25:
                _update_price_snapshot(tid, "price_15m", price)
            if age_h >= 1.0:
                _update_price_snapshot(tid, "price_1h", price)
            if age_h >= 2.0:
                _update_price_snapshot(tid, "price_2h", price)

            # TP / SL
            if price >= tp:
                _close_trade(tid, price, "TP")
                n_open -= 1
            elif price <= sl:
                _close_trade(tid, price, "SL")
                n_open -= 1

        # ── Check nieuwe STERK signalen (elke 5 min) ──────────────────────
        if now - last_signal_check >= SIGNAL_SEC and n_open < MAX_TRADES:
            last_signal_check = now
            try:
                _check_new_signals(n_open)
            except Exception as e:
                log.warning(f"[TestBot] check_new_signals: {e}")

        time.sleep(MONITOR_SEC)

    log.info("[TestBot] Loop gestopt")


def _check_new_signals(n_open: int):
    """
    Lees recente signalen uit SQLite signal_context.
    Score elk signal via historical_context (PostgreSQL via jojo_analytics).
    Open een trade als verdict == STERK en < MAX_TRADES.
    """
    try:
        sc  = sqlite3.connect(DB_PATH)
        cur = sc.cursor()
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        cur.execute("""
            SELECT symbol, signal, entry_price, ts
            FROM signal_context
            WHERE ts >= ? AND status = 'open'
            ORDER BY ts DESC LIMIT 20
        """, (cutoff,))
        fresh = cur.fetchall()
        sc.close()
    except Exception as e:
        log.warning(f"[TestBot] signal_context lezen: {e}")
        return

    if not fresh:
        return

    # Welke symbols hebben al een open trade?
    conn = get_conn()
    cur2 = conn.cursor()
    cur2.execute(adapt_query("SELECT DISTINCT symbol FROM testbot_trades WHERE status='open'"))
    open_syms = {r[0] for r in cur2.fetchall()}
    conn.close()

    for sym, sig, ep, ts in fresh:
        if n_open >= MAX_TRADES:
            break
        if sym in open_syms:
            continue

        # Historische score opvragen
        rows = _sj_query(f"""
            SELECT
                COUNT(*) AS n,
                AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100 AS win_pct,
                AVG(pnl_1h_pct) AS avg_pnl
            FROM historical_context
            WHERE symbol = '{sym}' AND signal = '{sig}'
            AND pnl_1h_pct IS NOT NULL
        """)
        if not rows:
            continue

        row    = rows[0]
        n_hist = int(row.get("n") or 0)
        win_pct = float(row.get("win_pct") or 0)
        avg_pnl = float(row.get("avg_pnl") or 0)

        score, verdict = _compute_score(win_pct, avg_pnl, n_hist)

        if verdict == "STERK":
            price = _binance_price(sym) or (float(ep) if ep else None)
            if price:
                _open_trade(sym, sig, score, price)
                open_syms.add(sym)
                n_open += 1


def manual_open(symbol: str, signal: str, setup_score: int = 0) -> dict:
    """Handmatige open (voor tests of vanuit apex_engine)."""
    price = _binance_price(symbol)
    if not price:
        return {"ok": False, "msg": f"Geen Binance prijs voor {symbol}"}
    ensure_table()
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("SELECT COUNT(*) FROM testbot_trades WHERE status='open'"))
    n_open = cur.fetchone()[0]
    conn.close()
    if n_open >= MAX_TRADES:
        return {"ok": False, "msg": f"Max {MAX_TRADES} open trades bereikt"}
    _open_trade(symbol, signal, setup_score, price)
    return {"ok": True, "symbol": symbol, "signal": signal,
            "entry_price": price, "tp_pct": TP_PCT, "sl_pct": SL_PCT}


# ── Publieke API ──────────────────────────────────────────────────────────────

def start_bot() -> dict:
    if _bot["running"]:
        return {"ok": False, "msg": "Bot draait al"}
    _bot["running"] = True
    t = threading.Thread(target=_bot_loop, daemon=True, name="testbot")
    _bot["thread"] = t
    t.start()
    log.info("[TestBot] Gestart")
    return {"ok": True, "msg": "TestBot gestart"}


def stop_bot() -> dict:
    if not _bot["running"]:
        return {"ok": False, "msg": "Bot draait niet"}
    _bot["running"] = False
    log.info("[TestBot] Stopsignaal gestuurd")
    return {"ok": True, "msg": "TestBot gestopt"}


def bot_status() -> dict:
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(adapt_query("SELECT COUNT(*) FROM testbot_trades WHERE status='open'"))
    n_open = cur.fetchone()[0] or 0

    cur.execute(adapt_query("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN net_pnl_usd > 0 THEN 1 ELSE 0 END) AS wins,
               SUM(net_pnl_usd) AS total_net,
               SUM(fee_usd) AS total_fee
        FROM testbot_trades WHERE status='closed'
    """))
    stats_row = cur.fetchone()
    conn.close()

    total = int(stats_row[0] or 0)
    wins  = int(stats_row[1] or 0)
    return {
        "running":     _bot["running"],
        "n_open":      n_open,
        "free_slots":  MAX_TRADES - n_open,
        "config": {
            "stake_usd":  STAKE_USD,
            "max_trades": MAX_TRADES,
            "tp_pct":     TP_PCT,
            "sl_pct":     SL_PCT,
            "max_hours":  MAX_HOURS,
            "fee_pct":    FEE_PCT,
        },
        "stats_all": {
            "total_trades":  total,
            "wins":          wins,
            "losses":        total - wins,
            "winrate_pct":   round(wins / total * 100, 1) if total else None,
            "total_net_usd": round(float(stats_row[2] or 0), 2),
            "total_fee_usd": round(float(stats_row[3] or 0), 2),
        }
    }
