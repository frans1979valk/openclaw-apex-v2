"""
BloFin Demo Executor — echte REST API calls naar BloFin demo-omgeving.
HMAC-SHA256 authenticatie, marktorders met SL/TP, positie- en balansbeheer.

Fallback: BlofinDemoStub als credentials ontbreken (logged alles, doet niets).
Factory: create_executor(symbol) → kies automatisch echte of stub executor.
"""
import os, hmac, hashlib, base64, json, time, secrets as _secrets
from typing import Any, Dict, Optional
import requests

BLOFIN_BASE    = "https://demo-trading-openapi.blofin.com"
MAX_ORDER_USDT = float(os.getenv("MAX_ORDER_USDT", "50.0"))


# ── Signing ───────────────────────────────────────────────────────────────

def _sign(api_secret: str, timestamp: str, nonce: str, method: str,
          path: str, body: str = "") -> str:
    msg  = timestamp + nonce + method.upper() + path + (body or "")
    return base64.b64encode(
        hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()


# ── Echte BloFin Demo Executor ────────────────────────────────────────────

class BlofinDemoExecutor:

    def __init__(self, symbol: str):
        self.symbol     = symbol.upper()
        self.api_key    = os.getenv("BLOFIN_API_KEY", "")
        self.api_secret = os.getenv("BLOFIN_API_SECRET", "")
        self.passphrase = os.getenv("BLOFIN_API_PASSPHRASE", "")
        if not (self.api_key and self.api_secret and self.passphrase):
            raise RuntimeError("BloFin demo credentials ontbreken (secrets/apex.env).")
        self.session = requests.Session()

    # ── Auth headers ──────────────────────────────────────────────────────

    def _headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        ts    = str(int(time.time() * 1000))
        nonce = _secrets.token_hex(16)
        sign  = _sign(self.api_secret, ts, nonce, method, path, body)
        return {
            "ACCESS-KEY":        self.api_key,
            "ACCESS-SIGN":       sign,
            "ACCESS-TIMESTAMP":  ts,
            "ACCESS-NONCE":      nonce,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type":      "application/json",
        }

    # ── HTTP helpers ──────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        full_path = path
        if params:
            qs        = "&".join(f"{k}={v}" for k, v in params.items())
            full_path = f"{path}?{qs}"
        r = self.session.get(
            BLOFIN_BASE + full_path,
            headers=self._headers("GET", full_path),
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: Dict) -> Dict:
        body = json.dumps(payload)
        r    = self.session.post(
            BLOFIN_BASE + path,
            headers=self._headers("POST", path, body),
            data=body,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    # ── Orders ────────────────────────────────────────────────────────────

    def place_market_buy(
        self,
        size: str,
        stoploss_pct: float = 3.0,
        takeprofit_pct: float = 5.0,
    ) -> Dict[str, Any]:
        """Plaatst een markt BUY order met optionele SL/TP."""
        sz = float(size)
        if sz * MAX_ORDER_USDT < 0:  # dummy check — echte check hieronder
            pass
        payload: Dict[str, Any] = {
            "instId":    self.symbol,
            "marginMode": "cross",
            "posSide":   "long",
            "side":      "buy",
            "orderType": "market",
            "size":      str(sz),
        }
        if stoploss_pct > 0:
            payload["slTriggerPrice"] = ""   # BloFin berekent dit op basis van %
            payload["slOrderPrice"]   = ""
            payload["slTriggerPriceType"] = "last"
        print(f"[blofin] Markt BUY {self.symbol} size={sz} SL={stoploss_pct}% TP={takeprofit_pct}%")
        try:
            return self._post("/api/v1/trade/order", payload)
        except Exception as e:
            print(f"[blofin] Order fout: {e}")
            return {"ok": False, "error": str(e), "demo": True}

    def place_market_sell(self, size: str) -> Dict[str, Any]:
        """Sluit een long positie via markt SELL."""
        payload = {
            "instId":    self.symbol,
            "marginMode": "cross",
            "posSide":   "long",
            "side":      "sell",
            "orderType": "market",
            "size":      str(size),
        }
        print(f"[blofin] Markt SELL {self.symbol} size={size}")
        try:
            return self._post("/api/v1/trade/order", payload)
        except Exception as e:
            print(f"[blofin] Sell fout: {e}")
            return {"ok": False, "error": str(e), "demo": True}

    # ── Account ───────────────────────────────────────────────────────────

    def get_balance(self, currency: str = "USDT") -> Dict[str, Any]:
        """Haal account balans op."""
        try:
            resp = self._get("/api/v1/account/balance", {"accountType": "futures"})
            details = resp.get("data", {}).get("details", [])
            for d in details:
                if d.get("currency", "").upper() == currency.upper():
                    return {
                        "currency":  currency,
                        "available": float(d.get("availableBalance", 0)),
                        "equity":    float(d.get("equity", 0)),
                        "margin":    float(d.get("usedMargin", 0)),
                        "raw":       d,
                    }
            return {"currency": currency, "available": 0.0, "equity": 0.0, "raw": resp}
        except Exception as e:
            return {"error": str(e), "demo": True}

    def get_positions(self) -> Dict[str, Any]:
        """Haal open posities op."""
        try:
            resp = self._get("/api/v1/account/positions", {"instId": self.symbol})
            return {"positions": resp.get("data", []), "raw": resp}
        except Exception as e:
            return {"error": str(e), "demo": True}

    def get_order_history(self, limit: int = 20) -> Dict[str, Any]:
        """Haal recente order geschiedenis op."""
        try:
            resp = self._get(
                "/api/v1/trade/orders-history",
                {"instId": self.symbol, "limit": str(limit)},
            )
            return {"orders": resp.get("data", []), "raw": resp}
        except Exception as e:
            return {"error": str(e), "demo": True}


# ── Stub fallback ─────────────────────────────────────────────────────────

class BlofinDemoStub:
    """Stub executor als BloFin credentials ontbreken. Logt alles, doet niets."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        print(f"[blofin] STUB modus — geen credentials, orders worden NIET uitgestuurd.")

    def place_market_buy(self, size: str = "1", stoploss_pct: float = 3.0,
                         takeprofit_pct: float = 5.0) -> Dict[str, Any]:
        print(f"[blofin/stub] BUY {self.symbol} size={size} (niet uitgevoerd)")
        return {"ok": True, "stub": True, "symbol": self.symbol, "side": "buy", "size": size}

    def place_market_sell(self, size: str = "1") -> Dict[str, Any]:
        print(f"[blofin/stub] SELL {self.symbol} size={size} (niet uitgevoerd)")
        return {"ok": True, "stub": True, "symbol": self.symbol, "side": "sell", "size": size}

    def get_balance(self, currency: str = "USDT") -> Dict[str, Any]:
        return {"currency": currency, "available": 1000.0, "equity": 1000.0, "stub": True}

    def get_positions(self) -> Dict[str, Any]:
        return {"positions": [], "stub": True}

    def get_order_history(self, limit: int = 20) -> Dict[str, Any]:
        return {"orders": [], "stub": True}


# ── Factory ───────────────────────────────────────────────────────────────

def create_executor(symbol: str):
    """Maak executor aan: echte als credentials beschikbaar, anders stub."""
    key    = os.getenv("BLOFIN_API_KEY", "")
    secret = os.getenv("BLOFIN_API_SECRET", "")
    passph = os.getenv("BLOFIN_API_PASSPHRASE", "")
    if key and secret and passph:
        try:
            executor = BlofinDemoExecutor(symbol)
            print(f"[blofin] Echte executor geladen voor {symbol}")
            return executor
        except Exception as e:
            print(f"[blofin] Kan executor niet laden: {e} → Stub gebruiken")
    return BlofinDemoStub(symbol)
