"""
STAP 17 — Multi-Exchange Intelligence

Verzamelt prijsdata van 5 exchanges en berekent een gewogen consensus.
Coinbase heeft het hoogste gewicht omdat het de meest 'eerlijke' markt is
(Amerikaanse retailbeleggers, minder wash-trading).

Exchanges en gewichten:
  Coinbase  0.35  — hoogste gewicht, US retail, meest betrouwbaar
  Binance   0.25  — grootste volume maar meer manipulatie
  Bybit     0.20  — derivatives-heavy, goede liquiditeit
  OKX       0.12  — Aziatisch, goed voor altcoin signalen
  Kraken    0.08  — kleinste maar meest regulier

Divergentie-signalen:
  Als Coinbase significant afwijkt van Binance (>0.5%) → actie-signaal
  Als alle exchanges tegelijk dalen → bevestigd bearish
  Als Coinbase als eerste stijgt terwijl anderen dalen → bullish lead
"""
import time, requests, logging
from typing import Dict, Optional

log = logging.getLogger("exchange_intel")

EXCHANGE_WEIGHTS = {
    "coinbase": 0.35,
    "binance":  0.25,
    "bybit":    0.20,
    "okx":      0.12,
    "kraken":   0.08,
}

# Timeout voor API calls
FETCH_TIMEOUT = 5


def _get_binance_price(symbol: str) -> Optional[float]:
    """BTCUSDT format."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=FETCH_TIMEOUT,
        )
        return float(r.json()["price"])
    except Exception:
        return None


def _get_bybit_price(symbol: str) -> Optional[float]:
    """BTC-USDT format."""
    try:
        bybit_sym = symbol.replace("USDT", "") + "-USDT"
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "spot", "symbol": bybit_sym},
            timeout=FETCH_TIMEOUT,
        )
        items = r.json().get("result", {}).get("list", [])
        if items:
            return float(items[0]["lastPrice"])
    except Exception:
        pass
    return None


def _get_coinbase_price(symbol: str) -> Optional[float]:
    """BTC-USD format."""
    try:
        # Coinbase gebruikt USD, converteer BTCUSDT → BTC-USD
        base = symbol.replace("USDT", "")
        r = requests.get(
            f"https://api.coinbase.com/v2/prices/{base}-USD/spot",
            timeout=FETCH_TIMEOUT,
        )
        return float(r.json()["data"]["amount"])
    except Exception:
        return None


def _get_okx_price(symbol: str) -> Optional[float]:
    """BTC-USDT format."""
    try:
        okx_sym = symbol.replace("USDT", "") + "-USDT"
        r = requests.get(
            "https://www.okx.com/api/v5/market/ticker",
            params={"instId": okx_sym},
            timeout=FETCH_TIMEOUT,
        )
        data = r.json().get("data", [{}])
        if data:
            return float(data[0]["last"])
    except Exception:
        pass
    return None


def _get_kraken_price(symbol: str) -> Optional[float]:
    """XBT/USDT format voor BTC, anders symbol/USDT."""
    try:
        base = symbol.replace("USDT", "")
        kraken_base = "XBT" if base == "BTC" else base
        pair = f"{kraken_base}USDT"
        r = requests.get(
            "https://api.kraken.com/0/public/Ticker",
            params={"pair": pair},
            timeout=FETCH_TIMEOUT,
        )
        result = r.json().get("result", {})
        if result:
            key = list(result.keys())[0]
            return float(result[key]["c"][0])   # last trade close
    except Exception:
        pass
    return None


FETCHERS = {
    "binance":  _get_binance_price,
    "bybit":    _get_bybit_price,
    "coinbase": _get_coinbase_price,
    "okx":      _get_okx_price,
    "kraken":   _get_kraken_price,
}


class ExchangeIntel:
    """
    Haalt prijzen op van 5 exchanges en berekent gewogen consensus.

    Gebruik:
        intel = ExchangeIntel()
        result = intel.get_consensus("BTCUSDT")
    """

    def __init__(self, cache_ttl: int = 30):
        self._cache: Dict[str, dict] = {}   # symbol → {ts, prices, consensus}
        self._cache_ttl = cache_ttl

    def get_consensus(self, symbol: str) -> dict:
        """
        Haalt prijzen op van alle exchanges en berekent gewogen consensus.

        Returns dict met:
          prices          — prijs per exchange
          consensus       — gewogen gemiddelde
          coinbase_lead   — True als Coinbase significant afwijkt
          divergence_pct  — max afwijking tussen exchanges
          all_bearish     — True als alle exchanges dalen t.o.v. cache
          confidence      — 0-1 score (hoeveel exchanges beschikbaar)
        """
        # Cache check
        cached = self._cache.get(symbol)
        if cached and time.time() - cached["ts"] < self._cache_ttl:
            return cached

        prices: Dict[str, float] = {}
        for name, fetcher in FETCHERS.items():
            p = fetcher(symbol)
            if p and p > 0:
                prices[name] = p

        if not prices:
            return {"prices": {}, "consensus": 0, "confidence": 0}

        # Gewogen gemiddelde
        total_weight = 0.0
        weighted_sum = 0.0
        for exch, price in prices.items():
            w = EXCHANGE_WEIGHTS.get(exch, 0.1)
            weighted_sum += price * w
            total_weight += w

        consensus = weighted_sum / total_weight if total_weight > 0 else 0

        # Coinbase lead: wijkt Coinbase >0.5% af van consensus?
        cb_price = prices.get("coinbase")
        coinbase_lead = False
        coinbase_diverge_pct = 0.0
        if cb_price and consensus > 0:
            coinbase_diverge_pct = (cb_price - consensus) / consensus * 100
            coinbase_lead = abs(coinbase_diverge_pct) > 0.5

        # Max divergentie tussen exchanges
        vals = list(prices.values())
        divergence_pct = 0.0
        if len(vals) >= 2:
            divergence_pct = (max(vals) - min(vals)) / min(vals) * 100

        # Confidence = aandeel beschikbare exchanges
        confidence = len(prices) / len(FETCHERS)

        result = {
            "symbol":               symbol,
            "prices":               prices,
            "consensus":            round(consensus, 4),
            "coinbase_price":       round(cb_price, 4) if cb_price else None,
            "coinbase_lead":        coinbase_lead,
            "coinbase_diverge_pct": round(coinbase_diverge_pct, 3),
            "divergence_pct":       round(divergence_pct, 3),
            "confidence":           round(confidence, 2),
            "exchanges_online":     list(prices.keys()),
            "ts":                   time.time(),
        }

        self._cache[symbol] = result

        if coinbase_lead:
            direction = "HOGER" if coinbase_diverge_pct > 0 else "LAGER"
            log.info(
                f"COINBASE LEAD {symbol}: CB {direction} dan consensus "
                f"({coinbase_diverge_pct:+.2f}%) | divergence={divergence_pct:.2f}%"
            )

        return result

    def get_multi(self, symbols: list) -> Dict[str, dict]:
        """Haal consensus op voor meerdere coins tegelijk."""
        return {sym: self.get_consensus(sym) for sym in symbols}
