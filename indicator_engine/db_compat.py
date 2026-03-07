"""Database compatibility layer — PostgreSQL met SQLite-achtige interface.

Alle services importeren `get_conn()` in plaats van `sqlite3.connect()`.
PostgreSQL wordt gebruikt als DATABASE_URL is geconfigureerd, anders SQLite fallback.

Gebruik:
    from db_compat import get_conn

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM events WHERE ts > %s", (ts,))
    rows = cur.fetchall()
    conn.commit()
    conn.close()

Let op: PostgreSQL gebruikt %s placeholders, SQLite gebruikt ?.
Gebruik get_placeholder() om het juiste formaat te krijgen.
"""
import os
import logging

log = logging.getLogger("db_compat")

DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_PATH = os.getenv("SQLITE_PATH", "/var/apex/apex.db")

_use_pg = bool(DATABASE_URL)

if _use_pg:
    import psycopg2
    import psycopg2.extras
    log.info(f"Database: PostgreSQL ({DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'configured'})")
else:
    import sqlite3
    log.info(f"Database: SQLite ({SQLITE_PATH})")


def get_conn():
    """Retourneer een database connectie (PostgreSQL of SQLite)."""
    if _use_pg:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def get_dict_conn():
    """Retourneer een connectie met dict-achtige rows (voor beide backends)."""
    if _use_pg:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn, True
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn, False


def dict_cursor(conn):
    """Maak een cursor die dict-achtige rows retourneert."""
    if _use_pg:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        return conn.cursor()


def ph():
    """Retourneer de juiste placeholder: %s voor PostgreSQL, ? voor SQLite."""
    return "%s" if _use_pg else "?"


def is_pg():
    """True als PostgreSQL wordt gebruikt."""
    return _use_pg


def adapt_query(sql: str) -> str:
    """Converteer SQLite syntax naar PostgreSQL als nodig.

    - ? → %s (placeholders)
    - datetime('now', '-N days') → NOW() - INTERVAL 'N days'
    - datetime('now') → NOW()
    - INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
    - AUTOINCREMENT → (verwijderd, SERIAL doet dit)
    """
    if _use_pg:
        import re
        # datetime('now', ?) with parametrized interval → NOW() + ?::interval
        # Must be done BEFORE ? → %s replacement
        sql = re.sub(r"datetime\('now',\s*\?\)", "NOW() + ?::interval", sql)
        sql = sql.replace("?", "%s")
        sql = re.sub(r"datetime\('now',\s*'-(\d+)\s+days'\)", r"NOW() - INTERVAL '\1 days'", sql)
        sql = re.sub(r"datetime\('now',\s*'-(\d+)\s+hours'\)", r"NOW() - INTERVAL '\1 hours'", sql)
        sql = re.sub(r"datetime\('now',\s*'(-\d+\s+\w+)'\)", r"NOW() + INTERVAL '\1'", sql)
        sql = sql.replace("datetime('now')", "NOW()")
        _had_ignore = "INSERT OR IGNORE" in sql
        sql = sql.replace("INSERT OR IGNORE", "INSERT")
        # ROUND(expr, N) → ROUND((expr)::numeric, N) for PostgreSQL
        sql = re.sub(r'ROUND\(([^,]+),\s*(\d+)\)', r'ROUND((\1)::numeric, \2)', sql)
        # MAX(a, b) scalar → GREATEST(a, b) for PostgreSQL
        sql = re.sub(r'\bMAX\(([^,)]+),\s*([^)]+)\)', r'GREATEST(\1, \2)', sql)
        # AUTOINCREMENT → not needed (SERIAL handles this)
        sql = sql.replace("AUTOINCREMENT", "")
        sql = sql.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
        if _had_ignore:
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql
