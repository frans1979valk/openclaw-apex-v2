import requests
from typing import Optional

class BybitFeed:
    def __init__(self, symbol: str):
        # XRP-USDT -> XRPUSDT
        self.symbol = symbol.replace("-", "")

    def get_last_price(self) -> Optional[float]:
        try:
            r = requests.get(
                "https://api.bybit.com/v5/market/tickers",
                params={"category": "spot", "symbol": self.symbol},
                timeout=5
            )
            r.raise_for_status()
            data = r.json()
            return float(data["result"]["list"][0]["lastPrice"])
        except Exception:
            return None
