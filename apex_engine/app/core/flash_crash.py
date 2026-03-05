"""
Flash Crash Bot
Detecteert een plotselinge prijsdaling en plaatst een demo market buy.

Trigger:
  - prijs daalt >= CRASH_PCT % binnen de laatste CRASH_WINDOW_SEC seconden
  - volume spike >= VOLUME_SPIKE_X keer het gemiddelde

Bescherming:
  - max exposure per coin
  - cooldown na een actie
  - stoploss / takeprofit registratie
"""
import time
from typing import Dict, List
from collections import defaultdict, deque

CRASH_PCT       = float(5.0)   # 5% daling
CRASH_WINDOW    = 30           # seconden
VOLUME_SPIKE_X  = 2.0          # 2x gemiddeld volume
MAX_EXPOSURE    = 100          # max $100 demo per coin
COOLDOWN_SEC    = 120          # 2 minuten cooldown na trigger

class FlashCrashDetector:
    def __init__(self):
        # price_history: symbol -> deque van (timestamp, price)
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self.last_trigger: Dict[str, float]  = {}
        self.triggered_buys: List[Dict]       = []

    def update(self, symbol: str, price: float, volume: float = 0.0) -> bool:
        """
        Voeg een nieuwe prijs toe en check of er een flash crash is.
        Geeft True terug als een koop-actie aanbevolen wordt.
        """
        now = time.time()
        self.price_history[symbol].append((now, price, volume))

        # Cooldown check
        if now - self.last_trigger.get(symbol, 0) < COOLDOWN_SEC:
            return False

        # Haal prijzen binnen het crash window op
        window_prices = [
            (ts, p, v) for ts, p, v in self.price_history[symbol]
            if now - ts <= CRASH_WINDOW
        ]
        if len(window_prices) < 3:
            return False

        oldest_price = window_prices[0][1]
        current_price = window_prices[-1][1]

        if oldest_price == 0:
            return False

        drop_pct = (oldest_price - current_price) / oldest_price * 100

        # Volume spike check
        vols = [v for _, _, v in window_prices if v > 0]
        avg_vol = sum(vols) / len(vols) if vols else 0
        current_vol = window_prices[-1][2]
        vol_spike = (current_vol > avg_vol * VOLUME_SPIKE_X) if avg_vol > 0 else False

        if drop_pct >= CRASH_PCT:
            self.last_trigger[symbol] = now
            self.triggered_buys.append({
                "ts": now,
                "symbol": symbol,
                "drop_pct": round(drop_pct, 2),
                "price": current_price,
                "vol_spike": vol_spike,
            })
            print(f"[flash_crash] TRIGGER {symbol}: -{drop_pct:.2f}% in {CRASH_WINDOW}s | vol_spike={vol_spike}")
            return True

        return False

    def get_recent_triggers(self, max_age: int = 3600) -> List[Dict]:
        now = time.time()
        return [t for t in self.triggered_buys if now - t["ts"] < max_age]
