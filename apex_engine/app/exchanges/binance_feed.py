import requests
from typing import Optional, List, Dict

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
    def get_top_movers(n: int = 30) -> List[Dict]:
        """Haal top N USDT pairs op gesorteerd op 24h volume."""
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr",
                timeout=10
            )
            r.raise_for_status()
            tickers = [
                t for t in r.json()
                if t["symbol"].endswith("USDT")
                and not t["symbol"].endswith("DOWNUSDT")
                and not t["symbol"].endswith("UPUSDT")
                and float(t["quoteVolume"]) > 1_000_000
            ]
            tickers.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
            return [
                {
                    "symbol": t["symbol"],
                    "price": float(t["lastPrice"]),
                    "change_pct": float(t["priceChangePercent"]),
                    "volume_usdt": float(t["quoteVolume"]),
                    "high": float(t["highPrice"]),
                    "low": float(t["lowPrice"]),
                }
                for t in tickers[:n]
            ]
        except Exception:
            return []
