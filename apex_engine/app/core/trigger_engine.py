"""
STAP 15 — Event-Driven Trigger Engine

Vervangt hardcoded timer-loops met een reactief event systeem.
Events worden gefired zodra marktcondities veranderen, niet op vaste intervallen.

Beschikbare events:
  price_spike      — prijs beweegt >X% in 5 min
  price_drop       — prijs daalt >X% (pre-crash signaal)
  volume_spike     — volume >3× het gemiddelde
  perfect_day      — PERFECT_DAY signaal gedetecteerd
  win_rate_crash   — win-rate daalt onder drempel
  news_alert       — breaking crypto nieuws (via news_monitor)
  signal_change    — signaal verandert van HOLD naar iets actiefs

Gebruik:
    engine = TriggerEngine()
    engine.on("price_spike", my_handler)
    engine.check(sym, price, vol, signal, win_rate)
"""
import time
import logging
from collections import defaultdict, deque
from typing import Callable, Dict, List, Optional

log = logging.getLogger("trigger_engine")

# Drempelwaarden
PRICE_SPIKE_PCT   = 2.0    # % stijging in 5 min
PRICE_DROP_PCT    = 3.0    # % daling in 5 min (pre-crash)
VOLUME_SPIKE_MULT = 3.0    # keer het gemiddeld volume
WIN_RATE_CRASH    = 40.0   # % — win-rate grens
EVENT_COOLDOWN    = 300    # seconden tussen gelijke events per coin


class TriggerEngine:
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=30))
        self._volume_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=30))
        self._last_event: Dict[str, float] = {}   # (sym, event) → timestamp
        self._last_signal: Dict[str, str] = {}    # sym → vorig signaal

    def on(self, event: str, handler: Callable) -> None:
        """Registreer een callback voor een event."""
        self._handlers[event].append(handler)
        log.debug(f"Handler geregistreerd voor event: {event}")

    def _fire(self, event: str, **kwargs) -> None:
        """Fire een event naar alle geregistreerde handlers."""
        sym = kwargs.get("symbol", "")
        key = f"{sym}:{event}"
        now = time.time()

        # Cooldown check — voorkomt spam
        if now - self._last_event.get(key, 0) < EVENT_COOLDOWN:
            return

        self._last_event[key] = now
        log.info(f"EVENT: {event} | {sym} | {kwargs}")

        for handler in self._handlers.get(event, []):
            try:
                handler(event=event, **kwargs)
            except Exception as e:
                log.error(f"Handler fout voor {event}: {e}")

        # Altijd ook "any_event" handlers aanroepen
        for handler in self._handlers.get("any_event", []):
            try:
                handler(event=event, **kwargs)
            except Exception as e:
                log.error(f"any_event handler fout: {e}")

    def check(
        self,
        symbol: str,
        price: float,
        volume: float,
        signal: str,
        rsi: Optional[float] = None,
        win_rate: Optional[float] = None,
        pre_crash_score: float = 0.0,
    ) -> List[str]:
        """
        Controleer een coin op events. Geeft lijst van gefirde events terug.

        Args:
            symbol:          Coin symbool (bijv. BTCUSDT)
            price:           Huidige prijs
            volume:          Huidige volume in USDT
            signal:          Huidig signaal (BUY, HOLD, PERFECT_DAY, etc.)
            rsi:             RSI waarde (optioneel)
            win_rate:        Huidige win-rate % (optioneel)
            pre_crash_score: Score 0-100 van pre_crash_detector
        """
        fired = []
        now = time.time()

        # Sla prijs en volume op
        self._price_history[symbol].append((now, price))
        self._volume_history[symbol].append(volume)

        # ── Price spike / drop ────────────────────────────────────────────
        hist = self._price_history[symbol]
        if len(hist) >= 2:
            # Vergelijk met prijs van ~5 min geleden (max 6 datapunten terug)
            lookback = min(6, len(hist) - 1)
            old_ts, old_price = hist[-lookback - 1]
            if old_price > 0 and (now - old_ts) < 600:   # max 10 min terug
                pct_change = (price - old_price) / old_price * 100

                if pct_change >= PRICE_SPIKE_PCT:
                    self._fire("price_spike", symbol=symbol, price=price,
                               change_pct=round(pct_change, 2), rsi=rsi)
                    fired.append("price_spike")

                elif pct_change <= -PRICE_DROP_PCT:
                    self._fire("price_drop", symbol=symbol, price=price,
                               change_pct=round(pct_change, 2), rsi=rsi,
                               pre_crash_score=pre_crash_score)
                    fired.append("price_drop")

        # ── Volume spike ─────────────────────────────────────────────────
        vol_hist = list(self._volume_history[symbol])
        if len(vol_hist) >= 5:
            avg_vol = sum(vol_hist[:-1]) / (len(vol_hist) - 1)
            if avg_vol > 0 and volume >= avg_vol * VOLUME_SPIKE_MULT:
                self._fire("volume_spike", symbol=symbol, price=price,
                           volume=volume, avg_volume=round(avg_vol),
                           multiplier=round(volume / avg_vol, 1))
                fired.append("volume_spike")

        # ── Perfect day ───────────────────────────────────────────────────
        if signal == "PERFECT_DAY":
            self._fire("perfect_day", symbol=symbol, price=price, rsi=rsi)
            fired.append("perfect_day")

        # ── Signal change ─────────────────────────────────────────────────
        prev = self._last_signal.get(symbol)
        if prev is not None and prev != signal:
            active = signal in ("BUY", "PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM")
            if active:
                self._fire("signal_change", symbol=symbol, price=price,
                           signal=signal, prev_signal=prev, rsi=rsi)
                fired.append("signal_change")
        self._last_signal[symbol] = signal

        # ── Win rate crash ────────────────────────────────────────────────
        if win_rate is not None and win_rate < WIN_RATE_CRASH:
            self._fire("win_rate_crash", symbol=symbol, win_rate=win_rate)
            fired.append("win_rate_crash")

        # ── Pre-crash drempel ─────────────────────────────────────────────
        if pre_crash_score >= 70:
            self._fire("pre_crash_warning", symbol=symbol, price=price,
                       score=pre_crash_score)
            fired.append("pre_crash_warning")

        return fired
