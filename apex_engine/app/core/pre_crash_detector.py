"""
STAP 16 — Pre-Crash Detector

Berekent een crash-risico score 0-100 op basis van:
  - Orderbook imbalance  (bid/ask druk)
  - Volume divergentie   (vol spike + prijs daalt)
  - RSI overbought + daling
  - Snelle prijsdaling   (momentum)
  - BTC dominantie shift (als BTC crasht, volgt de rest)

IJZEREN WET (nooit overrulen):
  Score >= 60 → STOP met kopen. VERMIJDEN of SHORT.
  Score >= 80 → NOODSIGNAAL. Alleen SHORT toegestaan.

Achtergrondinformatie:
  De eigenaar verloor $5000 door een dip te kopen (catching a falling knife).
  Dit systeem bestaat om dat te voorkomen. NOOIT kopen tijdens een crash.
"""
import time, requests, logging
from collections import deque
from typing import Dict, Optional

log = logging.getLogger("pre_crash")

# Drempelwaarden
ORDERBOOK_IMBALANCE_THRESH = 0.35   # bid/(bid+ask) < 35% = bearish druk
RSI_DANGER_THRESHOLD       = 75     # RSI boven deze waarde = overbought
PRICE_DROP_1MIN_PCT        = -1.5   # % daling in 1 min = momentum crash
VOLUME_DIVERGE_MULT        = 2.0    # vol spike bij prijsdaling

# Score gewichten (totaal = 100)
W_ORDERBOOK  = 30
W_VOL_DIVERG = 25
W_RSI        = 20
W_MOMENTUM   = 25


def _fetch_orderbook(symbol: str, limit: int = 20) -> Optional[dict]:
    """Haal Binance orderbook op (bids/asks)."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/depth",
            params={"symbol": symbol, "limit": limit},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.debug(f"Orderbook fout {symbol}: {e}")
        return None


class PreCrashDetector:
    """
    Berekent per coin een crash-risico score (0-100).
    Hogere score = meer kans op crash.

    Gebruik:
        detector = PreCrashDetector()
        score = detector.score("BTCUSDT", price=65000, rsi=78, volume=50_000_000)
    """

    def __init__(self):
        # Prijs- en volume-geschiedenis per coin
        self._prices:  Dict[str, deque] = {}
        self._volumes: Dict[str, deque] = {}
        self._scores:  Dict[str, float] = {}   # laatste scores
        self._last_fetch: Dict[str, float] = {}  # cooldown voor orderbook calls

    def _get_history(self, sym: str) -> tuple:
        if sym not in self._prices:
            self._prices[sym]  = deque(maxlen=20)
            self._volumes[sym] = deque(maxlen=20)
        return self._prices[sym], self._volumes[sym]

    def score(
        self,
        symbol: str,
        price: float,
        rsi: Optional[float] = None,
        volume: float = 0.0,
    ) -> float:
        """
        Bereken crash-risico score voor een coin.

        Returns:
            float 0-100. >= 60 = gevaar, >= 80 = kritiek.
        """
        p_hist, v_hist = self._get_history(symbol)
        p_hist.append((time.time(), price))
        v_hist.append(volume)

        total_score = 0.0

        # ── 1. Orderbook imbalance ─────────────────────────────────────
        # Haal maximaal 1x per 30 sec op (niet te agressief)
        now = time.time()
        ob_score = 0.0
        if now - self._last_fetch.get(symbol, 0) > 30:
            self._last_fetch[symbol] = now
            ob = _fetch_orderbook(symbol, limit=10)
            if ob:
                bid_vol = sum(float(b[1]) for b in ob.get("bids", []))
                ask_vol = sum(float(a[1]) for a in ob.get("asks", []))
                total   = bid_vol + ask_vol
                if total > 0:
                    bid_ratio = bid_vol / total
                    # Weinig bids = verkoopdruk → hoge score
                    if bid_ratio < ORDERBOOK_IMBALANCE_THRESH:
                        ob_score = (ORDERBOOK_IMBALANCE_THRESH - bid_ratio) / ORDERBOOK_IMBALANCE_THRESH
                        ob_score = min(1.0, ob_score * 1.5)  # versterken

        total_score += ob_score * W_ORDERBOOK

        # ── 2. Volume divergentie ─────────────────────────────────────
        # Hoog volume + dalende prijs = dump signal
        vol_score = 0.0
        if len(v_hist) >= 5 and len(p_hist) >= 5:
            avg_vol = sum(list(v_hist)[:-1]) / (len(v_hist) - 1)
            if avg_vol > 0:
                vol_ratio = volume / avg_vol
                prices = [p for _, p in p_hist]
                price_change = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0

                if vol_ratio >= VOLUME_DIVERGE_MULT and price_change < 0:
                    # Volume hoog maar prijs daalt = bearish divergentie
                    vol_score = min(1.0, (vol_ratio / VOLUME_DIVERGE_MULT - 1) * 0.5 +
                                    abs(price_change) * 10)

        total_score += vol_score * W_VOL_DIVERG

        # ── 3. RSI overbought ─────────────────────────────────────────
        rsi_score = 0.0
        if rsi is not None and rsi >= RSI_DANGER_THRESHOLD:
            rsi_score = (rsi - RSI_DANGER_THRESHOLD) / (100 - RSI_DANGER_THRESHOLD)
            rsi_score = min(1.0, rsi_score)

        total_score += rsi_score * W_RSI

        # ── 4. Prijs momentum (1-min daling) ──────────────────────────
        mom_score = 0.0
        if len(p_hist) >= 3:
            recent_prices = [p for _, p in list(p_hist)[-3:]]
            mom_pct = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100 \
                      if recent_prices[0] > 0 else 0
            if mom_pct < PRICE_DROP_1MIN_PCT:
                mom_score = min(1.0, abs(mom_pct) / abs(PRICE_DROP_1MIN_PCT) * 0.7)

        total_score += mom_score * W_MOMENTUM

        final = round(min(100.0, total_score), 1)
        self._scores[symbol] = final

        if final >= 60:
            log.warning(
                f"PRE-CRASH [{symbol}]: score={final} | "
                f"ob={ob_score:.2f} vol={vol_score:.2f} rsi={rsi_score:.2f} mom={mom_score:.2f}"
            )

        return final

    def get_score(self, symbol: str) -> float:
        """Geeft de laatste berekende score terug (0 als nog niet berekend)."""
        return self._scores.get(symbol, 0.0)

    def is_safe_to_buy(self, symbol: str, threshold: float = 60.0) -> bool:
        """
        IJZEREN WET check: is het veilig om te kopen?
        Geeft False als crash-risico te hoog is.
        """
        s = self.get_score(symbol)
        if s >= threshold:
            log.warning(f"IJZEREN WET: {symbol} score={s} >= {threshold} — KOPEN VERBODEN")
            return False
        return True

    def all_scores(self) -> Dict[str, float]:
        """Geeft alle huidige scores terug."""
        return dict(self._scores)
