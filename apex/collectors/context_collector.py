"""
signal_context collector — slaat indicator-snapshot op bij elk nieuw signaal.

Werking:
  1. Kijk welke signal_performance IDs nog geen context hebben
  2. Haal voor elke coin de indicatoren op via jojo_analytics (POST /indicators)
  3. Sla op in signal_context tabel in apex.db

Aanroep:
  python3 /root/.openclaw/workspace/tools/context_collector.py

Geen AI-calls. Alleen jojo_analytics intern (http://jojo_analytics:8097).
Bedoeld om elke 5-10 minuten via cron te draaien.

Voor opname in Apex repo: zie README_context_collector.md in dezelfde map.
"""
import sqlite3
import requests
import json
import logging
import os
import sys
from datetime import datetime, timezone

# setup_judge importeren vanuit dezelfde map
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from setup_judge import judge as _judge
    JUDGE_AVAILABLE = True
except ImportError:
    JUDGE_AVAILABLE = False

DB_PATH  = os.getenv("APEX_DB",            "/var/apex/apex.db")
ANA_BASE = os.getenv("ANALYTICS_URL",      "http://jojo_analytics:8097")
LOG_FILE = os.getenv("OPENCLAW_TOOLS_LOG", "/var/apex/openclaw_tools.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [context_collector] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("context_collector")


# ─── DB SETUP ────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS signal_context (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_perf_id  INTEGER NOT NULL UNIQUE,
    ts              TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    signal          TEXT NOT NULL,

    -- Prijs
    entry_price     REAL,

    -- Trend
    tf_bias         TEXT,

    -- RSI (1h)
    rsi_1h          REAL,
    rsi_oversold    INTEGER,    -- 1 als rsi_1h < 35
    rsi_overbought  INTEGER,    -- 1 als rsi_1h > 65

    -- MACD
    macd_hist       REAL,
    macd_signal     TEXT,       -- 'bullish' / 'bearish'

    -- Bollinger Bands
    bb_width        REAL,
    bb_position     TEXT,       -- 'low' / 'mid' / 'high'

    -- ADX (trendsterkte)
    adx             REAL,
    adx_strong      INTEGER,    -- 1 als adx > 25

    -- Stochastic RSI
    stoch_rsi_k     REAL,
    stoch_rsi_d     REAL,

    -- EMA alignment
    ema21           REAL,
    ema55           REAL,
    ema200          REAL,
    ema_bull        INTEGER,    -- 1 als ema21 > ema55 > ema200

    -- Engine advies
    advies          TEXT,

    -- Ruwe JSON (voor toekomstige features)
    raw_json        TEXT,
    collected_at    TEXT NOT NULL
);
"""


VERDICT_DDL = """
CREATE TABLE IF NOT EXISTS verdict_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_perf_id  INTEGER NOT NULL UNIQUE,
    ts              TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    signal          TEXT NOT NULL,
    rsi_1h          REAL,
    macd_signal     TEXT,
    adx             REAL,
    rsi_zone        TEXT,
    adx_strong      INTEGER,
    verdict         TEXT NOT NULL,   -- SKIP / TWIJFEL / TOESTAAN / ONBEKEND
    confidence      TEXT,            -- laag / midden / hoog
    n               INTEGER,
    avg_1h          REAL,
    avg_4h          REAL,
    win_pct_1h      REAL,
    conflict        INTEGER,         -- 1 als niveaus conflicteren
    matched_level   TEXT,            -- generiek / coin_rsi / coin_algemeen
    reden           TEXT,
    logged_at       TEXT NOT NULL
);
"""


def ensure_table(con: sqlite3.Connection) -> None:
    con.execute(DDL)
    con.execute(VERDICT_DDL)
    con.commit()


# ─── CORE LOGICA ─────────────────────────────────────────────────────────────

def get_uncollected(con: sqlite3.Connection) -> list:
    """Geef signal_performance rijen zonder context, nieuwste eerst."""
    return con.execute("""
        SELECT sp.id, sp.ts, sp.symbol, sp.signal, sp.entry_price
        FROM signal_performance sp
        LEFT JOIN signal_context sc ON sc.signal_perf_id = sp.id
        WHERE sc.id IS NULL
        ORDER BY sp.id DESC
        LIMIT 50
    """).fetchall()


def fetch_indicators(symbol: str) -> dict | None:
    """Haal indicator snapshot op via jojo_analytics POST /indicators."""
    try:
        r = requests.post(
            f"{ANA_BASE}/indicators",
            json={"symbol": symbol, "interval": "1h", "limit": 200},
            timeout=8,
        )
        r.raise_for_status()
        d = r.json()
        # /indicators geeft geen "ok" veld — check op aanwezigheid van "symbol"
        return d if d.get("symbol") else None
    except Exception as e:
        log.warning(f"indicators fout {symbol}: {e}")
        return None


def save_context(con: sqlite3.Connection, sp_id: int, ts: str, symbol: str,
                 signal: str, entry_price: float, ind: dict) -> None:
    rsi = ind.get("rsi")
    con.execute("""
        INSERT OR IGNORE INTO signal_context (
            signal_perf_id, ts, symbol, signal, entry_price,
            tf_bias,
            rsi_1h, rsi_oversold, rsi_overbought,
            macd_hist, macd_signal,
            bb_width, bb_position,
            adx, adx_strong,
            stoch_rsi_k, stoch_rsi_d,
            ema21, ema55, ema200, ema_bull,
            advies, raw_json, collected_at
        ) VALUES (
            ?,?,?,?,?,  ?,  ?,?,?,  ?,?,  ?,?,  ?,?,  ?,?,  ?,?,?,?,  ?,?,?
        )
    """, (
        sp_id, ts, symbol, signal, entry_price,
        ind.get("tf_bias"),
        rsi,
        1 if rsi is not None and rsi < 35 else 0,
        1 if rsi is not None and rsi > 65 else 0,
        ind.get("macd_hist"),
        ind.get("macd_signal"),
        ind.get("bb_width"),
        ind.get("bb_position"),
        ind.get("adx"),
        1 if ind.get("adx") is not None and ind["adx"] > 25 else 0,
        ind.get("stoch_rsi_k"),
        ind.get("stoch_rsi_d"),
        ind.get("ema21"),
        ind.get("ema55"),
        ind.get("ema200"),
        1 if ind.get("ema_bull") else 0,
        ind.get("advies"),
        json.dumps(ind, ensure_ascii=False),
        datetime.now(timezone.utc).isoformat(),
    ))
    con.commit()


def save_placeholder(con: sqlite3.Connection, sp_id: int, ts: str, symbol: str,
                     signal: str, entry_price: float) -> None:
    """Sla placeholder op als indicators tijdelijk niet beschikbaar zijn."""
    con.execute("""
        INSERT OR IGNORE INTO signal_context (
            signal_perf_id, ts, symbol, signal, entry_price,
            advies, raw_json, collected_at
        ) VALUES (?,?,?,?,?,?,?,?)
    """, (
        sp_id, ts, symbol, signal, entry_price,
        "NO_DATA",
        json.dumps({"ok": False, "reason": "indicators_unavailable"}),
        datetime.now(timezone.utc).isoformat(),
    ))
    con.commit()


# ─── MAIN ────────────────────────────────────────────────────────────────────

def save_verdict(con: sqlite3.Connection, sp_id: int, ts: str, symbol: str,
                 signal: str, ind: dict) -> None:
    """Roep setup_judge aan en sla verdict op in verdict_log."""
    if not JUDGE_AVAILABLE:
        return
    try:
        result = _judge(
            symbol=symbol,
            signal=signal,
            rsi=ind.get("rsi"),
            macd=ind.get("macd_signal"),
            adx=ind.get("adx"),
        )
        # Welk niveau was de primaire bron?
        matched = next(
            (k for k in ["generiek", "coin_rsi", "coin_algemeen"]
             if k in result.get("levels", {})), None
        )
        con.execute("""
            INSERT OR IGNORE INTO verdict_log (
                signal_perf_id, ts, symbol, signal,
                rsi_1h, macd_signal, adx, rsi_zone, adx_strong,
                verdict, confidence, n, avg_1h, avg_4h, win_pct_1h,
                conflict, matched_level, reden, logged_at
            ) VALUES (?,?,?,?, ?,?,?,?,?, ?,?,?,?,?,?, ?,?,?,?)
        """, (
            sp_id, ts, symbol, signal,
            ind.get("rsi"), ind.get("macd_signal"), ind.get("adx"),
            result.get("rsi_zone"), result.get("adx_strong"),
            result["verdict"], result.get("confidence"), result.get("n"),
            result.get("avg_1h"), result.get("avg_4h"), result.get("win_pct_1h"),
            1 if result.get("conflict") else 0,
            matched,
            result.get("reden", ""),
            datetime.now(timezone.utc).isoformat(),
        ))
        con.commit()
        log.info(
            f"  verdict={result['verdict']} confidence={result.get('confidence')} "
            f"n={result.get('n')} matched={matched}"
        )
    except Exception as e:
        log.warning(f"Verdict logging mislukt voor id={sp_id}: {e}")


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    ensure_table(con)

    rows = get_uncollected(con)
    if not rows:
        log.info("Geen nieuwe signalen.")
        con.close()
        return

    log.info(f"{len(rows)} nieuwe signalen te verwerken.")
    saved = failed = 0

    for sp_id, ts, symbol, signal, entry_price in rows:
        ind = fetch_indicators(symbol)
        if ind:
            save_context(con, sp_id, ts, symbol, signal, entry_price, ind)
            log.info(
                f"✓ {symbol} {signal} (id={sp_id}) "
                f"RSI={ind.get('rsi')} MACD={ind.get('macd_signal')} "
                f"ADX={ind.get('adx')} BB={ind.get('bb_position')}"
            )
            save_verdict(con, sp_id, ts, symbol, signal, ind)
            saved += 1
        else:
            save_placeholder(con, sp_id, ts, symbol, signal, entry_price)
            log.warning(f"✗ {symbol} (id={sp_id}) — placeholder opgeslagen")
            failed += 1

    log.info(f"Klaar: {saved} opgeslagen, {failed} placeholders.")
    con.close()


if __name__ == "__main__":
    main()
