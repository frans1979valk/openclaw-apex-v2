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
