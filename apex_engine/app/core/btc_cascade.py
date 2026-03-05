"""
STAP 17 — BTC Cascade Short Detector

Na een BTC crash volgen de altcoins altijd: ETH, SOL, BNB, XRP.
Dit systeem detecteert een BTC-daling en triggert cascade-short signalen
in volgorde van historische correlatie-snelheid.

CASCADE VOLGORDE (gebaseerd op historische lag-analyse):
  1. ETH  — volgt BTC binnen 1-3 min  (0.98 correlatie)
  2. BNB  — volgt BTC binnen 2-5 min  (0.94 correlatie)
  3. SOL  — volgt BTC binnen 3-7 min  (0.91 correlatie)
  4. XRP  — volgt BTC binnen 5-10 min (0.88 correlatie)

IJZEREN WET: Dit systeem genereert ALLEEN SHORT signalen.
              NOOIT kopen tijdens of na een BTC crash.
"""
import time, logging
from collections import deque
from typing import Dict, List, Optional, Callable

log = logging.getLogger("btc_cascade")

# BTC daling drempel om cascade te starten
BTC_DROP_TRIGGER_PCT  = -3.0    # % daling in 5 min → cascade start
BTC_DROP_SEVERE_PCT   = -6.0    # % daling → emergency cascade (hogere urgentie)
CASCADE_COOLDOWN       = 1800   # sec — wacht 30 min voor nieuwe cascade

# Cascade volgorde: (symbol, lag_min, correlatie)
CASCADE_ORDER = [
    ("ETHUSDT",  2,  0.98),
    ("BNBUSDT",  4,  0.94),
    ("SOLUSDT",  5,  0.91),
    ("XRPUSDT",  8,  0.88),
]


class BtcCascadeDetector:
    """
    Monitort BTC prijsbeweging en triggert cascade SHORT signalen.

    Gebruik:
        detector = BtcCascadeDetector()
        detector.on_cascade(my_handler)  # handler(coins, btc_drop_pct, urgentie)
        detector.update("BTCUSDT", price=65000)
    """

    def __init__(self):
        self._btc_prices: deque = deque(maxlen=40)  # ~40 datapunten = ~6 min bij 10s interval
        self._last_cascade: float = 0.0
        self._handlers: List[Callable] = []
        self._cascade_active: bool = False
        self._cascade_start: float = 0.0
        self._cascade_symbols: List[str] = []

    def on_cascade(self, handler: Callable) -> None:
        """Registreer callback: handler(coins, btc_drop_pct, urgentie)."""
        self._handlers.append(handler)

    def update(self, symbol: str, price: float) -> Optional[dict]:
        """
        Update BTC prijs en controleer op cascade condities.

        Args:
            symbol: Moet "BTCUSDT" zijn voor cascade check
            price:  Huidige prijs

        Returns:
            dict met cascade info als een cascade gefired is, anders None.
        """
        if "BTC" not in symbol:
            return None

        now = time.time()
        self._btc_prices.append((now, price))

        if len(self._btc_prices) < 5:
            return None

        # Bereken BTC daling over afgelopen ~5 min
        prices = list(self._btc_prices)
        lookback = min(30, len(prices) - 1)   # ~5 min bij 10s polls

        old_ts, old_price = prices[-lookback - 1]
        if old_price <= 0 or (now - old_ts) > 600:
            return None

        drop_pct = (price - old_price) / old_price * 100

        # Check cascade trigger
        if drop_pct > BTC_DROP_TRIGGER_PCT:
            # Geen cascade — BTC daalt niet genoeg
            self._cascade_active = False
            return None

        if (now - self._last_cascade) < CASCADE_COOLDOWN:
            return None   # Cooldown actief

        # ── Cascade gevonden ─────────────────────────────────────────
        self._last_cascade = now
        self._cascade_active = True
        self._cascade_start = now

        urgentie = "CRITICAL" if drop_pct <= BTC_DROP_SEVERE_PCT else "HIGH"

        cascade_coins = [
            {
                "symbol":      sym,
                "lag_min":     lag,
                "correlation": corr,
                "expected_drop_pct": round(drop_pct * corr, 2),
            }
            for sym, lag, corr in CASCADE_ORDER
        ]

        result = {
            "type":          "BTC_CASCADE",
            "btc_drop_pct":  round(drop_pct, 2),
            "btc_price":     price,
            "urgentie":      urgentie,
            "cascade_coins": cascade_coins,
            "ts":            now,
        }

        log.warning(
            f"BTC CASCADE GEDETECTEERD: drop={drop_pct:.2f}% | "
            f"urgentie={urgentie} | cascade: {[c['symbol'] for c in cascade_coins]}"
        )

        # Fire handlers
        for handler in self._handlers:
            try:
                handler(
                    coins=cascade_coins,
                    btc_drop_pct=drop_pct,
                    urgentie=urgentie,
                    btc_price=price,
                )
            except Exception as e:
                log.error(f"Cascade handler fout: {e}")

        return result

    def get_cascade_coins_due(self) -> List[dict]:
        """
        Geeft terug welke cascade coins nu een SHORT signaal moeten krijgen
        op basis van de verwachte lag-tijd.
        """
        if not self._cascade_active:
            return []

        now = time.time()
        elapsed_min = (now - self._cascade_start) / 60
        due = []

        for sym, lag, corr in CASCADE_ORDER:
            if elapsed_min >= lag:
                due.append({"symbol": sym, "correlation": corr, "elapsed_min": elapsed_min})

        return due

    @property
    def is_cascade_active(self) -> bool:
        """True als een cascade de afgelopen 30 min actief was."""
        return self._cascade_active and (time.time() - self._cascade_start) < CASCADE_COOLDOWN
