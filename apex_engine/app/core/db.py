import os, sqlite3, json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

def init_db(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        source TEXT NOT NULL,
        level TEXT NOT NULL,
        title TEXT NOT NULL,
        payload_json TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        executor TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        size TEXT NOT NULL,
        price REAL,
        raw_json TEXT
    )""")
    # Signaal performance tabel — bijhoudt wat elk signaal opgeleverd had
    cur.execute("""CREATE TABLE IF NOT EXISTS signal_performance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        symbol TEXT NOT NULL,
        signal TEXT NOT NULL,
        active_signals TEXT,
        entry_price REAL NOT NULL,
        price_15m REAL,
        price_1h  REAL,
        price_4h  REAL,
        pnl_15m_pct REAL,
        pnl_1h_pct  REAL,
        pnl_4h_pct  REAL,
        status TEXT DEFAULT 'open'
    )""")
    # Market context memory — opslaan van multi-TF context per signaal
    cur.execute("""CREATE TABLE IF NOT EXISTS market_context(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        symbol TEXT NOT NULL,
        signal TEXT NOT NULL,
        entry_price REAL NOT NULL,
        rsi_5m REAL,
        tf_confirm_score INTEGER,
        tf_bias TEXT,
        tf_1h_rsi REAL,
        tf_4h_rsi REAL,
        outcome_1h_pct REAL,
        outcome_4h_pct REAL,
        status TEXT DEFAULT 'open'
    )""")
    # Demo account tracking — virtuele $1000 rekening
    cur.execute("""CREATE TABLE IF NOT EXISTS demo_account(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        price REAL NOT NULL,
        virtual_size_usdt REAL NOT NULL,
        virtual_pnl_usdt REAL DEFAULT 0,
        balance_after REAL NOT NULL,
        signal TEXT,
        note TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS demo_balance(
        id INTEGER PRIMARY KEY CHECK (id = 1),
        balance REAL NOT NULL DEFAULT 1000.0,
        peak_balance REAL NOT NULL DEFAULT 1000.0,
        total_trades INTEGER DEFAULT 0,
        winning_trades INTEGER DEFAULT 0,
        total_volume_usdt REAL DEFAULT 0
    )""")
    # Zorg dat er altijd 1 record is
    cur.execute("INSERT OR IGNORE INTO demo_balance(id, balance, peak_balance) VALUES (1, 1000.0, 1000.0)")

    # ── Historische data voor AI-geheugen ─────────────────────────────────
    # Prijs snapshots: elke 5 min per coin opgeslagen
    cur.execute("""CREATE TABLE IF NOT EXISTS price_snapshots(
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        symbol  TEXT NOT NULL,
        price   REAL NOT NULL,
        rsi     REAL,
        volume_usdt REAL,
        signal  TEXT,
        change_pct REAL,
        atr     REAL,
        tf_bias TEXT
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_sym_ts ON price_snapshots(symbol, ts)")

    # Pre-crash score geschiedenis: wanneer was het gevaarlijk?
    cur.execute("""CREATE TABLE IF NOT EXISTS crash_score_log(
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        symbol  TEXT NOT NULL,
        score   REAL NOT NULL,
        ob_pct  REAL,
        vol_pct REAL,
        rsi_pct REAL,
        mom_pct REAL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_csl_sym_ts ON crash_score_log(symbol, ts)")

    # Exchange consensus geschiedenis: prijsvergelijking over tijd
    cur.execute("""CREATE TABLE IF NOT EXISTS exchange_consensus_log(
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts              TEXT NOT NULL,
        symbol          TEXT NOT NULL,
        consensus       REAL,
        coinbase_price  REAL,
        binance_price   REAL,
        bybit_price     REAL,
        okx_price       REAL,
        kraken_price    REAL,
        blofin_price    REAL,
        divergence_pct  REAL,
        coinbase_lead   INTEGER DEFAULT 0
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ecl_sym_ts ON exchange_consensus_log(symbol, ts)")

    # Marktgebeurtenissen: BTC cascades, flash crashes, news alerts
    cur.execute("""CREATE TABLE IF NOT EXISTS market_events(
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        symbol      TEXT,
        severity    TEXT,
        value       REAL,
        description TEXT,
        payload_json TEXT
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_me_ts ON market_events(ts)")

    conn.commit()
    conn.close()

def log_event(db_path: str, source: str, level: str, title: str, payload: Dict[str, Any] | None = None) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    ts = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO events(ts, source, level, title, payload_json) VALUES (?, ?, ?, ?, ?)",
        (ts, source, level, title, json.dumps(payload or {}, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

def log_order(db_path: str, executor: str, symbol: str, side: str, size: str, price: float | None, raw: Any) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    ts = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO orders(ts, executor, symbol, side, size, price, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts, executor, symbol, side, size, price, json.dumps(raw, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

def log_signal_entry(db_path: str, symbol: str, signal: str,
                     entry_price: float, active_signals: List[str]) -> None:
    """Sla een nieuw signaal op voor latere performance evaluatie."""
    conn = sqlite3.connect(db_path)
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO signal_performance
           (ts, symbol, signal, active_signals, entry_price, status)
           VALUES (?, ?, ?, ?, ?, 'open')""",
        (ts, symbol, signal, json.dumps(active_signals), entry_price)
    )
    conn.commit()
    conn.close()

def evaluate_open_signals(db_path: str, symbol: str, current_price: float) -> None:
    """
    Kijk terug op eerdere open signalen voor dit symbol en vul de
    prijs in na 15 min, 1 uur en 4 uur. Bereken P&L %.
    """
    if not current_price:
        return
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ts, entry_price, price_15m, price_1h, price_4h FROM signal_performance "
        "WHERE symbol=? AND status='open'",
        (symbol,)
    )
    rows = cur.fetchall()
    for row in rows:
        sid, ts_str, entry, p15, p1h, p4h = row
        try:
            ts_entry = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        age = now - ts_entry
        updates = {}

        if p15 is None and age >= timedelta(minutes=15):
            updates["price_15m"] = current_price
            updates["pnl_15m_pct"] = round((current_price / entry - 1) * 100, 3)
        if p1h is None and age >= timedelta(hours=1):
            updates["price_1h"] = current_price
            updates["pnl_1h_pct"] = round((current_price / entry - 1) * 100, 3)
        if p4h is None and age >= timedelta(hours=4):
            updates["price_4h"] = current_price
            updates["pnl_4h_pct"] = round((current_price / entry - 1) * 100, 3)

        # Sluit na 4 uur
        if age >= timedelta(hours=4):
            updates["status"] = "closed"

        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE signal_performance SET {set_clause} WHERE id=?",
                (*updates.values(), sid)
            )
    conn.commit()
    conn.close()

def log_market_context(db_path: str, symbol: str, signal: str, entry_price: float,
                       rsi_5m: float = None, tf_confirm_score: int = None,
                       tf_bias: str = None, tf_detail: dict = None) -> None:
    """Sla market context op voor het learning geheugen."""
    conn = sqlite3.connect(db_path)
    ts = datetime.now(timezone.utc).isoformat()
    tf = tf_detail or {}
    rsi_1h = tf.get("1h", {}).get("rsi")
    rsi_4h = tf.get("4h", {}).get("rsi")
    conn.execute(
        """INSERT INTO market_context
           (ts, symbol, signal, entry_price, rsi_5m, tf_confirm_score, tf_bias, tf_1h_rsi, tf_4h_rsi)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ts, symbol, signal, entry_price, rsi_5m, tf_confirm_score, tf_bias, rsi_1h, rsi_4h)
    )
    conn.commit()
    conn.close()


DEMO_TRADE_SIZE_PCT = 0.05   # 5% van balans per trade (max $50)
DEMO_MAX_TRADE_USDT = 50.0

def demo_virtual_buy(db_path: str, symbol: str, price: float, signal: str) -> None:
    """Registreer een virtuele koop in de demo rekening."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT balance FROM demo_balance WHERE id=1")
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    balance = row[0]
    size_usdt = min(DEMO_MAX_TRADE_USDT, balance * DEMO_TRADE_SIZE_PCT)
    if size_usdt < 1.0:
        conn.close()
        return
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO demo_account(ts, symbol, action, price, virtual_size_usdt,
           virtual_pnl_usdt, balance_after, signal, note)
           VALUES (?, ?, 'buy', ?, ?, 0, ?, ?, ?)""",
        (ts, symbol, price, size_usdt, balance, signal, f"Auto-buy op {signal}")
    )
    conn.execute(
        "UPDATE demo_balance SET total_trades=total_trades+1, total_volume_usdt=total_volume_usdt+? WHERE id=1",
        (size_usdt,)
    )
    conn.commit()
    conn.close()


def demo_evaluate_trades(db_path: str, symbol: str, current_price: float) -> None:
    """Evalueer open demo trades en bereken P&L."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    cur.execute(
        "SELECT id, ts, price, virtual_size_usdt FROM demo_account "
        "WHERE symbol=? AND action='buy' AND virtual_pnl_usdt=0",
        (symbol,)
    )
    rows = cur.fetchall()
    for row in rows:
        tid, ts_str, buy_price, size_usdt = row
        try:
            age = now - datetime.fromisoformat(ts_str)
        except Exception:
            continue
        # Sluit positie na 1 uur (simulatie)
        if age.total_seconds() >= 3600 and buy_price and current_price:
            pnl_pct = (current_price / buy_price - 1)
            pnl_usdt = round(size_usdt * pnl_pct, 4)
            conn.execute(
                "UPDATE demo_account SET virtual_pnl_usdt=? WHERE id=?",
                (pnl_usdt, tid)
            )
            # Update balans en stats
            if pnl_usdt > 0:
                conn.execute(
                    "UPDATE demo_balance SET balance=balance+?, peak_balance=MAX(peak_balance, balance+?), "
                    "winning_trades=winning_trades+1 WHERE id=1",
                    (pnl_usdt, pnl_usdt)
                )
            else:
                conn.execute(
                    "UPDATE demo_balance SET balance=balance+? WHERE id=1",
                    (pnl_usdt,)
                )
    conn.commit()
    conn.close()


def get_demo_stats(db_path: str) -> dict:
    """Haal demo account statistieken op."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT balance, peak_balance, total_trades, winning_trades, total_volume_usdt FROM demo_balance WHERE id=1")
        row = cur.fetchone()
        if not row:
            conn.close()
            return {}
        balance, peak, total, wins, vol = row

        # Recente trades
        cur.execute("""
            SELECT ts, symbol, action, price, virtual_size_usdt, virtual_pnl_usdt, signal
            FROM demo_account ORDER BY id DESC LIMIT 10
        """)
        trades = cur.fetchall()
        conn.close()

        win_rate = round(wins / total * 100, 1) if total > 0 else 0
        pnl_total = round(balance - 1000.0, 2)
        return {
            "demo_start_usdt":    1000.0,
            "balance":            round(balance, 2),
            "peak_balance":       round(peak, 2),
            "pnl_total_usdt":     pnl_total,
            "pnl_total_pct":      round(pnl_total / 10, 2),  # % van $1000
            "total_orders":       total,
            "winning_trades":     wins,
            "win_rate_pct":       win_rate,
            "total_volume_usdt":  round(vol, 2),
            "avg_pnl_1h_pct":     0,  # wordt gevuld via signal_performance
            "signals_evaluated":  total,
            "recent_orders": [{
                "ts": t[0], "symbol": t[1], "side": t[2],
                "price": t[3], "size": round(t[4] / t[3], 6) if t[3] else 0,
                "pnl_usdt": t[5], "signal": t[6],
            } for t in trades],
        }
    except Exception as e:
        return {"error": str(e)}


def get_backtest_summaries(db_path: str, symbols: List[str]) -> dict:
    """
    Lees de meest recente historische backtest-resultaten uit de DB
    voor de opgegeven coins. Geeft per coin een samenvatting terug
    zodat de AI-agent historische context heeft.
    """
    if not symbols:
        return {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        result = {}
        for sym in symbols:
            cur.execute("""
                SELECT signal, COUNT(*) as cnt,
                       AVG(pnl_1h_pct) as avg1h, AVG(pnl_4h_pct) as avg4h,
                       AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100 as win1h,
                       MIN(candle_ts), MAX(candle_ts), months
                FROM historical_backtest
                WHERE symbol=?
                GROUP BY signal
                ORDER BY cnt DESC
            """, (sym,))
            rows = cur.fetchall()
            if rows:
                months = rows[0][7] if rows[0][7] is not None else "?"
                by_sig = {}
                for r in rows:
                    by_sig[r[0]] = {
                        "count": r[1],
                        "avg_pnl_1h": round(r[2] or 0, 3),
                        "avg_pnl_4h": round(r[3] or 0, 3),
                        "win_rate_1h": round(r[4] or 0, 1),
                    }
                result[sym] = {"months": months, "by_signal": by_sig}
        conn.close()
        return result
    except Exception:
        return {}
