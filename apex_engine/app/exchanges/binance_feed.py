import requests, time
from typing import Optional, List, Dict, Set

# Tokenized aandelen en grondstoffen op BloFin — geen crypto, anders gedrag
_BLOFIN_STOCK_TOKENS = {
    "PLTR", "COIN", "AMZN", "MSTR", "HOOD", "INTC", "NVDA", "TSLA",
    "AAPL", "GOOGL", "META", "MSFT", "NFLX", "AMD", "PYPL", "SQ",
    "CL", "XCU", "GC", "SI",  # grondstoffen
}

# Vaste whitelist — altijd goedgekeurd, geen Telegram overleg nodig
SAFE_COINS = {
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "LTCUSDT", "ATOMUSDT", "NEARUSDT", "UNIUSDT", "AAVEUSDT",
    "XLMUSDT", "ALGOUSDT", "INJUSDT", "OPUSDT", "ARBUSDT",
    "APTUSDT", "SEIUSDT", "SUIUSDT", "TIAUSDT", "FETUSDT",
    "RENDERUSDT", "JUPUSDT", "FTMUSDT", "SANDUSDT", "MANAUSDT",
    "VETUSDT", "HBARUSDT", "GRTUSDT", "MATICUSDT", "FILUSDT",
    "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "WIFUSDT",
}

# Cache voor BloFin beschikbare coins
_blofin_coins_cache: Set[str] = set()
_blofin_cache_ts: float = 0.0
_BLOFIN_CACHE_TTL = 3600   # 1 uur


def get_blofin_available_coins() -> Set[str]:
    """
    Haal alle beschikbare spot coins op van BloFin (in XRPUSDT formaat).
    Slaat tokenized aandelen en grondstoffen over.
    Cache: 1 uur.
    """
    global _blofin_coins_cache, _blofin_cache_ts
    if time.time() - _blofin_cache_ts < _BLOFIN_CACHE_TTL and _blofin_coins_cache:
        return _blofin_coins_cache

    try:
        r = requests.get(
            "https://openapi.blofin.com/api/v1/market/instruments",
            params={"instType": "SPOT"},
            timeout=8,
        )
        r.raise_for_status()
        coins: Set[str] = set()
        for inst in r.json().get("data", []):
            inst_id = inst.get("instId", "")
            if not inst_id.endswith("-USDT"):
                continue
            base = inst_id.replace("-USDT", "")
            if base in _BLOFIN_STOCK_TOKENS:
                continue   # sla tokenized aandelen over
            coins.add(base + "USDT")   # XRP-USDT → XRPUSDT
        _blofin_coins_cache = coins
        _blofin_cache_ts = time.time()
        print(f"[blofin_coins] {len(coins)} coins beschikbaar op BloFin spot")
        return coins
    except Exception as e:
        print(f"[blofin_coins] fout: {e} — val terug op SAFE_COINS")
        return SAFE_COINS


class BinanceFeed:
    def __init__(self, symbol: str = "XRPUSDT"):
        self.symbol = symbol.replace("-", "")

    def get_last_price(self) -> Optional[float]:
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": self.symbol},
                timeout=5
            )
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception:
            return None

    @staticmethod
    def get_top_movers(n: int = 40) -> List[Dict]:
        """
        Haal top N USDT pairs op van Binance, gefilterd op:
          1. Beschikbaar op BloFin spot (kan je écht kopen)
          2. Geen tokenized aandelen
          3. Minimaal $5M dagvolume

        Elke coin krijgt een 'is_new_coin' vlag als hij niet in SAFE_COINS zit
        maar wel op BloFin beschikbaar is. Kimi mag nieuwe coins SUGGEREREN
        maar de eigenaar moet ze goedkeuren via Telegram.
        """
        blofin_coins = get_blofin_available_coins()

        try:
            r = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr",
                timeout=10
            )
            r.raise_for_status()
            all_tickers = r.json()

            result = []
            for t in all_tickers:
                sym = t["symbol"]
                if not sym.endswith("USDT"):
                    continue
                if float(t["quoteVolume"]) < 5_000_000:
                    continue
                # Moet op BloFin beschikbaar zijn
                if sym not in blofin_coins:
                    continue
                is_new = sym not in SAFE_COINS
                result.append({
                    "symbol":      sym,
                    "price":       float(t["lastPrice"]),
                    "change_pct":  float(t["priceChangePercent"]),
                    "volume_usdt": float(t["quoteVolume"]),
                    "high":        float(t["highPrice"]),
                    "low":         float(t["lowPrice"]),
                    "is_new_coin": is_new,
                })

            # Sorteer: eerst safe coins op volume, dan nieuwe coins op volume
            result.sort(key=lambda x: (x["is_new_coin"], -x["volume_usdt"]))
            return result[:n]

        except Exception:
            return []
