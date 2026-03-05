"""
Data Logger — Historische opslag voor AI-geheugen

Slaat elke 5 minuten per coin op:
  - Prijs, RSI, volume, signaal (price_snapshots)
  - Pre-crash score (crash_score_log)
  - Exchange consensus (exchange_consensus_log)

En bij events meteen:
  - BTC cascade, flash crash, nieuws, pre-crash waarschuwing (market_events)

De AI kan via /history/{symbol} en /market-events inzichten halen uit
historische data: "vorige keer dat de crash score >70 was, daalde de prijs
gemiddeld X% in de volgende 30 minuten."
"""
import sqlite3, json, logging, time
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("data_logger")

# Hoe vaak snapshots opslaan (seconden)
SNAPSHOT_INTERVAL = 300   # elke 5 minuten
CRASH_LOG_INTERVAL = 60   # crash scores elke minuut (als score > 30)
EXCH_LOG_INTERVAL  = 600  # exchange consensus elke 10 minuten

_last_snapshot: dict = {}   # symbol → timestamp
_last_crash_log: dict = {}  # symbol → timestamp
_last_exch_log: dict  = {}  # symbol → timestamp


class DataLogger:
    """
    Centrale logger voor historische marktdata.

    Gebruik:
        logger = DataLogger("/var/apex/apex.db")
        logger.maybe_log_snapshot(symbol, price, rsi=45.2, ...)
        logger.log_market_event("BTC_CASCADE", symbol="BTCUSDT", ...)
    """

    def __init__(self, db_path: str):
        self._db = db_path

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)

    # ── Prijs snapshot ─────────────────────────────────────────────────────

    def maybe_log_snapshot(
        self,
        symbol: str,
        price: float,
        rsi: Optional[float] = None,
        volume_usdt: float = 0.0,
        signal: Optional[str] = None,
        change_pct: float = 0.0,
        atr: Optional[float] = None,
        tf_bias: Optional[str] = None,
    ) -> bool:
        """Sla snapshot op als het meer dan SNAPSHOT_INTERVAL geleden is."""
        now = time.time()
        if now - _last_snapshot.get(symbol, 0) < SNAPSHOT_INTERVAL:
            return False
        _last_snapshot[symbol] = now
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO price_snapshots
                   (ts, symbol, price, rsi, volume_usdt, signal, change_pct, atr, tf_bias)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, symbol, price, rsi, volume_usdt, signal, change_pct, atr, tf_bias),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log.debug(f"snapshot fout {symbol}: {e}")
            return False

    # ── Pre-crash score log ────────────────────────────────────────────────

    def maybe_log_crash_score(
        self,
        symbol: str,
        score: float,
        ob_pct: float = 0.0,
        vol_pct: float = 0.0,
        rsi_pct: float = 0.0,
        mom_pct: float = 0.0,
    ) -> bool:
        """Log crash score elke minuut (alleen als score > 30 of was > 30)."""
        now = time.time()
        interval = CRASH_LOG_INTERVAL if score > 30 else SNAPSHOT_INTERVAL
        if now - _last_crash_log.get(symbol, 0) < interval:
            return False
        _last_crash_log[symbol] = now
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO crash_score_log
                   (ts, symbol, score, ob_pct, vol_pct, rsi_pct, mom_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ts, symbol, score, ob_pct, vol_pct, rsi_pct, mom_pct),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log.debug(f"crash_score fout {symbol}: {e}")
            return False

    # ── Exchange consensus log ─────────────────────────────────────────────

    def maybe_log_exchange_consensus(
        self,
        symbol: str,
        consensus: Optional[float],
        prices: dict,
        divergence_pct: float = 0.0,
        coinbase_lead: bool = False,
    ) -> bool:
        """Log exchange prices elke 10 minuten."""
        now = time.time()
        if now - _last_exch_log.get(symbol, 0) < EXCH_LOG_INTERVAL:
            return False
        _last_exch_log[symbol] = now
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO exchange_consensus_log
                   (ts, symbol, consensus, coinbase_price, binance_price, bybit_price,
                    okx_price, kraken_price, blofin_price, divergence_pct, coinbase_lead)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts, symbol, consensus,
                    prices.get("coinbase"), prices.get("binance"), prices.get("bybit"),
                    prices.get("okx"), prices.get("kraken"), prices.get("blofin"),
                    divergence_pct, int(coinbase_lead),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log.debug(f"exchange_consensus fout {symbol}: {e}")
            return False

    # ── Markt events ───────────────────────────────────────────────────────

    def log_market_event(
        self,
        event_type: str,
        symbol: Optional[str] = None,
        severity: Optional[str] = None,
        value: Optional[float] = None,
        description: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        """
        Log een marktgebeurtenis meteen (geen cooldown).

        event_type voorbeelden:
          BTC_CASCADE, FLASH_CRASH, PRE_CRASH_WARNING,
          NEWS_PANIC, NEWS_BULLISH, COINBASE_LEAD,
          TRADING_HALTED, TRADING_RESUMED
        """
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO market_events
                   (ts, event_type, symbol, severity, value, description, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts, event_type, symbol, severity, value, description,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            conn.close()
            log.info(f"EVENT logged: {event_type} | {symbol} | {description}")
        except Exception as e:
            log.warning(f"market_event fout: {e}")

    # ── Query helpers voor AI ──────────────────────────────────────────────

    def get_recent_snapshots(self, symbol: str, hours: int = 24) -> list:
        """Haal recente prijs snapshots op (voor AI context)."""
        try:
            conn = self._conn()
            rows = conn.execute(
                """SELECT ts, price, rsi, signal, change_pct, tf_bias
                   FROM price_snapshots
                   WHERE symbol=?
                   AND ts >= datetime('now', ?)
                   ORDER BY ts DESC LIMIT 200""",
                (symbol, f"-{hours} hours"),
            ).fetchall()
            conn.close()
            return [
                {"ts": r[0], "price": r[1], "rsi": r[2],
                 "signal": r[3], "change_pct": r[4], "tf_bias": r[5]}
                for r in rows
            ]
        except Exception:
            return []

    def get_crash_history(self, symbol: str, hours: int = 48) -> list:
        """Pre-crash scores over de afgelopen X uur."""
        try:
            conn = self._conn()
            rows = conn.execute(
                """SELECT ts, score FROM crash_score_log
                   WHERE symbol=? AND ts >= datetime('now', ?)
                   ORDER BY ts DESC LIMIT 500""",
                (symbol, f"-{hours} hours"),
            ).fetchall()
            conn.close()
            return [{"ts": r[0], "score": r[1]} for r in rows]
        except Exception:
            return []

    def get_recent_events(self, hours: int = 72, event_type: Optional[str] = None) -> list:
        """Recente marktgebeurtenissen (voor AI context)."""
        try:
            conn = self._conn()
            if event_type:
                rows = conn.execute(
                    """SELECT ts, event_type, symbol, severity, value, description
                       FROM market_events
                       WHERE event_type=? AND ts >= datetime('now', ?)
                       ORDER BY ts DESC LIMIT 100""",
                    (event_type, f"-{hours} hours"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT ts, event_type, symbol, severity, value, description
                       FROM market_events
                       WHERE ts >= datetime('now', ?)
                       ORDER BY ts DESC LIMIT 100""",
                    (f"-{hours} hours",),
                ).fetchall()
            conn.close()
            return [
                {"ts": r[0], "type": r[1], "symbol": r[2],
                 "severity": r[3], "value": r[4], "description": r[5]}
                for r in rows
            ]
        except Exception:
            return []

    def get_ai_context_summary(self, symbol: str) -> dict:
        """
        Geeft een samenvatting van historische data voor de AI.
        Compact formaat zodat het in een prompt past.
        """
        try:
            conn = self._conn()

            # Gemiddelde prijs laatste 24u
            row = conn.execute(
                """SELECT AVG(price), MIN(price), MAX(price), COUNT(*)
                   FROM price_snapshots WHERE symbol=?
                   AND ts >= datetime('now', '-24 hours')""",
                (symbol,)
            ).fetchone()
            price_24h = {
                "avg": round(row[0] or 0, 6), "min": round(row[1] or 0, 6),
                "max": round(row[2] or 0, 6), "snapshots": row[3]
            } if row and row[0] else {}

            # Max crash score laatste 24u
            row2 = conn.execute(
                """SELECT MAX(score), AVG(score) FROM crash_score_log
                   WHERE symbol=? AND ts >= datetime('now', '-24 hours')""",
                (symbol,)
            ).fetchone()
            crash_24h = {
                "max_score": round(row2[0] or 0, 1),
                "avg_score": round(row2[1] or 0, 1)
            } if row2 and row2[0] else {}

            # Recente events voor dit symbol
            events = conn.execute(
                """SELECT event_type, severity, description, ts
                   FROM market_events WHERE symbol=? OR symbol IS NULL
                   AND ts >= datetime('now', '-48 hours')
                   ORDER BY ts DESC LIMIT 10""",
                (symbol,)
            ).fetchall()

            conn.close()
            return {
                "symbol":    symbol,
                "price_24h": price_24h,
                "crash_24h": crash_24h,
                "events":    [{"type": e[0], "sev": e[1], "desc": e[2], "ts": e[3]} for e in events],
            }
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}
