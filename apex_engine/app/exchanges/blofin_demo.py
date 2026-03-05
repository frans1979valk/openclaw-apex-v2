"""
Blofin Demo Trading Executor
Echte REST API calls naar https://demo-trading-openapi.blofin.com
met HMAC-SHA256 authenticatie
"""
import os
import time
import hmac
import hashlib
import base64
import requests
from typing import Any, Dict, List, Optional


BASE_URL = "https://demo-trading-openapi.blofin.com"
MAX_ORDER_USDT = float(os.getenv("MAX_ORDER_USDT", "50.0"))


def sign_request(timestamp: str, method: str, path: str, body: str, secret: str) -> str:
    message = timestamp + method + path + body
    signature = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    )
    return base64.b64encode(signature.digest()).decode()


class BlofinDemoExecutor:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.api_key = os.getenv("BLOFIN_API_KEY", "")
        self.api_secret = os.getenv("BLOFIN_API_SECRET", "")
        self.passphrase = os.getenv("BLOFIN_API_PASSPHRASE", "")

        if not (self.api_key and self.api_secret and self.passphrase):
            print("[blofin_demo] Credentials ontbreken — fallback naar BlofinDemoStub")

    def _headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signature = sign_request(timestamp, method, path, body, self.api_secret)

        return {
            "Content-Type": "application/json",
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
        }

    def _request(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
        if not (self.api_key and self.api_secret and self.passphrase):
            return {"error": "credentials_missing", "stub": True}

        url = BASE_URL + endpoint
        body_str = ""
        if payload:
            import json
            body_str = json.dumps(payload)

        headers = self._headers(method, endpoint, body_str)

        try:
            if method == "GET":
                r = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                r = requests.post(url, headers=headers, data=body_str, timeout=10)
            else:
                return {"error": "unsupported_method"}

            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def place_market_buy(self, size: str, stoploss_pct: float = 3.0, takeprofit_pct: float = 5.0) -> Dict[str, Any]:
        size_usdt = float(size)
        if size_usdt > MAX_ORDER_USDT:
            return {"error": f"order_size_exceeds_limit", "max": MAX_ORDER_USDT, "requested": size_usdt}

        payload = {
            "instId": self.symbol,
            "tdMode": "isolated",
            "side": "buy",
            "orderType": "market",
            "sz": str(size),
            "slTriggerPrice": "",
            "slOrdPrice": "",
            "tpTriggerPrice": "",
            "tpOrdPrice": "",
        }

        return self._request("POST", "/api/v1/trade/order", payload)

    def place_market_sell(self, size: str) -> Dict[str, Any]:
        size_usdt = float(size)
        if size_usdt > MAX_ORDER_USDT:
            return {"error": f"order_size_exceeds_limit", "max": MAX_ORDER_USDT, "requested": size_usdt}

        payload = {
            "instId": self.symbol,
            "tdMode": "isolated",
            "side": "sell",
            "orderType": "market",
            "sz": str(size),
        }

        return self._request("POST", "/api/v1/trade/order", payload)

    def get_balance(self, currency: str = "USDT") -> Dict[str, Any]:
        return self._request("GET", "/api/v1/asset/balances")

    def get_positions(self) -> List[Dict[str, Any]]:
        result = self._request("GET", "/api/v1/trade/positions")
        if isinstance(result, dict) and "data" in result:
            return result.get("data", [])
        return []

    def get_order_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        result = self._request("GET", f"/api/v1/trade/orders-history?limit={limit}")
        if isinstance(result, dict) and "data" in result:
            return result.get("data", [])
        return []


class BlofinDemoStub:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def place_market_buy(self, size: str, stoploss_pct: float = 3.0, takeprofit_pct: float = 5.0) -> Dict[str, Any]:
        return {
            "stub": True,
            "symbol": self.symbol,
            "side": "buy",
            "type": "market",
            "size": size,
            "stoploss_pct": stoploss_pct,
            "takeprofit_pct": takeprofit_pct
        }

    def place_market_sell(self, size: str) -> Dict[str, Any]:
        return {"stub": True, "symbol": self.symbol, "side": "sell", "type": "market", "size": size}

    def get_balance(self, currency: str = "USDT") -> Dict[str, Any]:
        return {"stub": True, "currency": currency, "available": "1000.00"}

    def get_positions(self) -> List[Dict[str, Any]]:
        return []

    def get_order_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return []


def create_executor(symbol: str):
    api_key = os.getenv("BLOFIN_API_KEY", "")
    api_secret = os.getenv("BLOFIN_API_SECRET", "")
    passphrase = os.getenv("BLOFIN_API_PASSPHRASE", "")

    if api_key and api_secret and passphrase:
        return BlofinDemoExecutor(symbol)
    else:
        print(f"[blofin_demo] Credentials ontbreken voor {symbol} — gebruik BlofinDemoStub")
        return BlofinDemoStub(symbol)
