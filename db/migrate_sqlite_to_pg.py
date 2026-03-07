#!/usr/bin/env python3
"""Migrate data from SQLite to PostgreSQL.

Run inside a container that has access to both /var/apex/apex.db and DATABASE_URL.
Usage: python3 db/migrate_sqlite_to_pg.py
"""
import os, sys, sqlite3
import psycopg2
from psycopg2.extras import execute_values

SQLITE_PATH = "/var/apex/apex.db"
DATABASE_URL = os.environ["DATABASE_URL"]

# Tables to migrate with their columns (matching PostgreSQL schema)
TABLES = {
    "events": ("ts", "source", "level", "title", "payload_json"),
    "orders": ("ts", "executor", "symbol", "side", "size", "price", "raw_json"),
    "proposals": ("ts", "agent", "params_json", "reason", "status"),
    "proposals_v2": ("id", "ts", "type", "payload_json", "reason", "requested_by", "requires_confirm", "status", "confirmed_at", "applied_at"),
    "signal_performance": ("ts", "symbol", "signal", "active_signals", "entry_price", "price_15m", "price_1h", "price_4h", "pnl_15m_pct", "pnl_1h_pct", "pnl_4h_pct", "status"),
    "historical_backtest": ("run_ts", "symbol", "interval", "months", "candle_ts", "signal", "active_signals", "entry_price", "price_1h", "price_4h", "price_24h", "pnl_1h_pct", "pnl_4h_pct", "pnl_24h_pct"),
    "market_context": ("ts", "symbol", "signal", "entry_price", "rsi_5m", "tf_confirm_score", "tf_bias", "tf_1h_rsi", "tf_4h_rsi"),
    "demo_account": ("ts", "symbol", "action", "price", "virtual_size_usdt", "virtual_pnl_usdt", "balance_after", "signal", "note"),
    "price_snapshots": ("ts", "symbol", "price", "rsi", "volume_usdt", "signal", "change_pct", "atr", "tf_bias"),
    "crash_score_log": ("ts", "symbol", "score", "ob_pct", "vol_pct", "rsi_pct", "mom_pct"),
    "exchange_consensus_log": ("ts", "symbol", "consensus", "coinbase_price", "binance_price", "bybit_price", "okx_price", "kraken_price", "blofin_price", "divergence_pct", "coinbase_lead"),
    "market_events": ("ts", "event_type", "symbol", "severity", "value", "description", "payload_json"),
    "otp_codes": ("email", "code", "expires_at"),
    "sessions": ("token", "email", "expires_at"),
    "ohlcv_history": ("symbol", "interval", "ts", "open", "high", "low", "close", "volume"),
}

# demo_balance is special — update instead of insert
DEMO_BALANCE_COLS = ("balance", "peak_balance", "total_trades", "winning_trades", "total_volume_usdt")


def migrate():
    print(f"Connecting to SQLite: {SQLITE_PATH}")
    sq = sqlite3.connect(SQLITE_PATH)
    sq.row_factory = sqlite3.Row

    print(f"Connecting to PostgreSQL...")
    pg = psycopg2.connect(DATABASE_URL)

    for table, cols in TABLES.items():
        cur_sq = sq.cursor()
        col_list = ", ".join(cols)
        cur_sq.execute(f"SELECT {col_list} FROM {table}")
        rows = cur_sq.fetchall()

        if not rows:
            print(f"  {table}: 0 rows (skip)")
            continue

        cur_pg = pg.cursor()
        # Clear existing data
        cur_pg.execute(f"DELETE FROM {table}")

        placeholders = ", ".join(["%s"] * len(cols))
        insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

        # For tables with SERIAL id, we need to reset the sequence after
        has_serial = table not in ("proposals_v2", "otp_codes", "sessions", "ohlcv_history")

        batch_size = 1000
        total = 0
        for i in range(0, len(rows), batch_size):
            batch = [tuple(row) for row in rows[i:i+batch_size]]
            cur_pg.executemany(insert_sql, batch)
            total += len(batch)

        # Reset sequence for SERIAL columns
        if has_serial:
            cur_pg.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))")

        pg.commit()
        print(f"  {table}: {total} rows migrated")

    # demo_balance special handling
    cur_sq = sq.cursor()
    cur_sq.execute(f"SELECT {', '.join(DEMO_BALANCE_COLS)} FROM demo_balance WHERE id=1")
    row = cur_sq.fetchone()
    if row:
        cur_pg = pg.cursor()
        set_clause = ", ".join(f"{c}=%s" for c in DEMO_BALANCE_COLS)
        cur_pg.execute(f"UPDATE demo_balance SET {set_clause} WHERE id=1", tuple(row))
        pg.commit()
        print(f"  demo_balance: updated (balance={row[0]}, trades={row[2]})")

    sq.close()
    pg.close()
    print("\nMigratie voltooid!")


if __name__ == "__main__":
    migrate()
