"""
Binance WebSocket Live Feed
- Multi-symbol 1m candle stream met historische seed
- Thread-safe CandleBuffer met deque(maxlen=500)
- Auto-reconnect bij verbindingsverlies
"""
import json
import time
import threading
import requests
from collections import deque
from typing import Dict, Callable, Optional, List
import websocket


class CandleBuffer:
    def __init__(self, symbol: str, maxlen: int = 500):
        self.symbol = symbol
        self.candles = deque(maxlen=maxlen)
        self.lock = threading.Lock()
        self.last_close_time = 0

    def seed_historical(self, limit: int = 250):
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": self.symbol, "interval": "1m", "limit": limit},
                timeout=10
            )
            r.raise_for_status()
            data = r.json()

            with self.lock:
                for kline in data:
                    ohlcv = {
                        "open_time": int(kline[0]),
                        "open": float(kline[1]),
                        "high": float(kline[2]),
                        "low": float(kline[3]),
                        "close": float(kline[4]),
                        "volume": float(kline[5]),
                        "close_time": int(kline[6]),
                    }
                    self.candles.append(ohlcv)
                    self.last_close_time = ohlcv["close_time"]

            print(f"[binance_ws] {self.symbol}: seeded {len(data)} historische candles")
        except Exception as e:
            print(f"[binance_ws] Seed fout {self.symbol}: {e}")

    def update_candle(self, kline_data: dict):
        with self.lock:
            k = kline_data["k"]
            ohlcv = {
                "open_time": k["t"],
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "close_time": k["T"],
            }

            if k["x"]:
                if ohlcv["close_time"] > self.last_close_time:
                    self.candles.append(ohlcv)
                    self.last_close_time = ohlcv["close_time"]
                    return True
            else:
                if self.candles and self.candles[-1]["open_time"] == ohlcv["open_time"]:
                    self.candles[-1] = ohlcv

        return False

    def get_candles(self) -> List[dict]:
        with self.lock:
            return list(self.candles)


class BinanceWebSocket:
    def __init__(self, symbols: List[str], on_candle_closed: Optional[Callable] = None):
        self.symbols = [s.lower() for s in symbols]
        self.on_candle_closed = on_candle_closed
        self.buffers: Dict[str, CandleBuffer] = {}
        self.ws: Optional[websocket.WebSocketApp] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.reconnect_delay = 5

        for sym in symbols:
            self.buffers[sym] = CandleBuffer(sym)
            self.buffers[sym].seed_historical(250)

    def _build_url(self) -> str:
        streams = [f"{s.lower()}@kline_1m" for s in self.symbols]
        return f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if "data" not in data:
                return

            kline_data = data["data"]
            symbol = kline_data["s"]

            if symbol in self.buffers:
                is_closed = self.buffers[symbol].update_candle(kline_data)

                if is_closed and self.on_candle_closed:
                    candles = self.buffers[symbol].get_candles()
                    if candles:
                        ohlcv = candles[-1]
                        self.on_candle_closed(symbol, ohlcv)

        except Exception as e:
            print(f"[binance_ws] Message parse fout: {e}")

    def _on_error(self, ws, error):
        print(f"[binance_ws] WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[binance_ws] Verbinding gesloten: {close_status_code} - {close_msg}")
        if self.running:
            print(f"[binance_ws] Auto-reconnect in {self.reconnect_delay}s...")
            time.sleep(self.reconnect_delay)
            if self.running:
                self._connect()

    def _on_open(self, ws):
        print(f"[binance_ws] Verbonden - streaming {len(self.symbols)} symbols")

    def _connect(self):
        url = self._build_url()
        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.ws.run_forever()

    def start(self):
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._connect, daemon=True)
        self.thread.start()
        print(f"[binance_ws] WebSocket thread gestart voor {self.symbols}")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
        if self.thread:
            self.thread.join(timeout=5)
        print("[binance_ws] WebSocket gestopt")

    def get_candles(self, symbol: str) -> List[dict]:
        if symbol in self.buffers:
            return self.buffers[symbol].get_candles()
        return []


def create_websocket(symbols: List[str], on_candle_closed: Optional[Callable] = None) -> BinanceWebSocket:
    ws = BinanceWebSocket(symbols, on_candle_closed)
    ws.start()
    return ws
