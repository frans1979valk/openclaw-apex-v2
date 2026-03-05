"""
Binance WebSocket — live 1m candle feed met historische seed.
Thread-safe CandleBuffer per symbol. Auto-reconnect bij verlies.
"""
import json, time, threading, requests
import numpy as np
from collections import deque
from typing import Callable, Dict, List, Optional
import websocket

BINANCE_REST  = "https://api.binance.com/api/v3/klines"
BINANCE_WS    = "wss://stream.binance.com:9443/stream"
SEED_CANDLES  = 250
BUFFER_SIZE   = 500
RECONNECT_SEC = 5


class CandleBuffer:
    """Thread-safe OHLCV buffer per symbol."""

    def __init__(self, symbol: str, maxlen: int = BUFFER_SIZE):
        self.symbol  = symbol
        self._lock   = threading.Lock()
        self._buf: deque = deque(maxlen=maxlen)

    def seed(self, candles: List[dict]) -> None:
        with self._lock:
            self._buf.clear()
            for c in candles:
                self._buf.append(c)

    def update(self, candle: dict) -> None:
        """Vervang laatste candle (open) of voeg nieuwe toe (closed)."""
        with self._lock:
            if self._buf and self._buf[-1]["ts"] == candle["ts"]:
                self._buf[-1] = candle  # update huidige open candle
            else:
                self._buf.append(candle)

    def to_arrays(self) -> Optional[Dict[str, np.ndarray]]:
        with self._lock:
            if len(self._buf) < 60:
                return None
            candles = list(self._buf)
        return {
            "open":   np.array([c["open"]   for c in candles], dtype=float),
            "high":   np.array([c["high"]   for c in candles], dtype=float),
            "low":    np.array([c["low"]    for c in candles], dtype=float),
            "close":  np.array([c["close"]  for c in candles], dtype=float),
            "volume": np.array([c["volume"] for c in candles], dtype=float),
        }

    def last_close(self) -> Optional[float]:
        with self._lock:
            return self._buf[-1]["close"] if self._buf else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


def _fetch_seed(symbol: str, interval: str = "1m", limit: int = SEED_CANDLES) -> List[dict]:
    """Haal historische candles op van Binance REST API als seed."""
    try:
        r = requests.get(
            BINANCE_REST,
            params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        return [
            {
                "ts":     int(k[0]),
                "open":   float(k[1]),
                "high":   float(k[2]),
                "low":    float(k[3]),
                "close":  float(k[4]),
                "volume": float(k[5]),
                "closed": True,
            }
            for k in r.json()
        ]
    except Exception as e:
        print(f"[binance_ws] Seed fout {symbol}: {e}")
        return []


class BinanceWebSocketFeed:
    """
    Beheert een gecombineerde Binance WebSocket stream voor meerdere symbols.
    Roept on_candle_closed(symbol, ohlcv_dict) aan bij elke afgesloten candle.
    """

    def __init__(
        self,
        symbols: List[str],
        interval: str = "1m",
        on_candle_closed: Optional[Callable] = None,
    ):
        self.symbols          = [s.lower() for s in symbols]
        self.interval         = interval
        self.on_candle_closed = on_candle_closed
        self.buffers: Dict[str, CandleBuffer] = {
            s.upper(): CandleBuffer(s.upper()) for s in symbols
        }
        self._ws: Optional[websocket.WebSocketApp] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ── Seed ──────────────────────────────────────────────────────────────
    def _seed_all(self) -> None:
        for sym in self.symbols:
            candles = _fetch_seed(sym.upper(), self.interval)
            if candles:
                self.buffers[sym.upper()].seed(candles)
                print(f"[binance_ws] Seed {sym.upper()}: {len(candles)} candles geladen")

    # ── WebSocket callbacks ───────────────────────────────────────────────
    def _on_message(self, ws, raw: str) -> None:
        try:
            msg  = json.loads(raw)
            data = msg.get("data", {})
            k    = data.get("k", {})
            if not k:
                return
            sym = k["s"].upper()
            candle = {
                "ts":     int(k["t"]),
                "open":   float(k["o"]),
                "high":   float(k["h"]),
                "low":    float(k["l"]),
                "close":  float(k["c"]),
                "volume": float(k["v"]),
                "closed": bool(k["x"]),
            }
            if sym in self.buffers:
                self.buffers[sym].update(candle)
                if candle["closed"] and self.on_candle_closed:
                    ohlcv = self.buffers[sym].to_arrays()
                    if ohlcv:
                        self.on_candle_closed(sym, ohlcv)
        except Exception as e:
            print(f"[binance_ws] Message fout: {e}")

    def _on_error(self, ws, err) -> None:
        print(f"[binance_ws] WS fout: {err}")

    def _on_close(self, ws, code, msg) -> None:
        print(f"[binance_ws] Verbinding verbroken (code={code}). Herverbinden na {RECONNECT_SEC}s...")

    def _on_open(self, ws) -> None:
        print(f"[binance_ws] Verbonden — {len(self.symbols)} symbols")

    # ── Verbinding ────────────────────────────────────────────────────────
    def _build_url(self) -> str:
        streams = "/".join(f"{s}@kline_{self.interval}" for s in self.symbols)
        return f"{BINANCE_WS}?streams={streams}"

    def _connect(self) -> None:
        url = self._build_url()
        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def _run_loop(self) -> None:
        """Auto-reconnect loop."""
        while self._running:
            try:
                self._connect()
            except Exception as e:
                print(f"[binance_ws] Verbindingsfout: {e}")
            if self._running:
                time.sleep(RECONNECT_SEC)
                print("[binance_ws] Herverbinden...")
                self._seed_all()  # herseed bij reconnect

    # ── Publieke API ──────────────────────────────────────────────────────
    def start(self) -> None:
        """Start WebSocket in achtergrondthread."""
        self._seed_all()
        self._running = True
        self._thread  = threading.Thread(target=self._run_loop, daemon=True, name="binance-ws")
        self._thread.start()
        print(f"[binance_ws] Feed gestart voor: {[s.upper() for s in self.symbols]}")

    def stop(self) -> None:
        self._running = False
        if self._ws:
            self._ws.close()

    def get_buffer(self, symbol: str) -> Optional[CandleBuffer]:
        return self.buffers.get(symbol.upper())

    def get_arrays(self, symbol: str) -> Optional[Dict[str, np.ndarray]]:
        buf = self.get_buffer(symbol)
        return buf.to_arrays() if buf else None
