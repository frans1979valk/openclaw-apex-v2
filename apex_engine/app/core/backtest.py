"""
Backtesting Engine
Test een strategie op historische Binance kline data.

Metrics: profit factor, max drawdown, win rate, sharpe ratio
"""
import requests
import numpy as np
import talib
from typing import Dict, List, Optional

def fetch_history(symbol: str, interval: str = "1h", limit: int = 500) -> Optional[Dict]:
    """Haal historische OHLCV data op van Binance."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        return {
            "ts":     [int(c[0]) for c in data],
            "open":   np.array([float(c[1]) for c in data]),
            "high":   np.array([float(c[2]) for c in data]),
            "low":    np.array([float(c[3]) for c in data]),
            "close":  np.array([float(c[4]) for c in data]),
            "volume": np.array([float(c[5]) for c in data]),
        }
    except Exception as e:
        print(f"[backtest] data fout: {e}")
        return None

def run(symbol: str, interval: str = "1h", limit: int = 500,
        fee_bps: float = 6.0) -> Dict:
    """
    Voer een backtest uit met de RSI+MACD+EMA strategie.
    Returns: dict met metrics en trade lijst.
    """
    data = fetch_history(symbol, interval, limit)
    if data is None:
        return {"error": "Geen data"}

    close = data["close"]
    high  = data["high"]
    low   = data["low"]

    # Indicatoren
    rsi       = talib.RSI(close, 14)
    macd, sig, hist = talib.MACD(close, 12, 26, 9)
    ema20     = talib.EMA(close, 20)
    ema50     = talib.EMA(close, 50)

    fee = fee_bps / 10000

    trades: List[Dict] = []
    position = None  # {"entry": price, "idx": i}

    for i in range(50, len(close)):
        if np.isnan(rsi[i]) or np.isnan(hist[i]) or np.isnan(ema20[i]) or np.isnan(ema50[i]):
            continue

        price = close[i]

        # BUY signaal
        if position is None:
            if rsi[i] < 35 and hist[i] > 0 and price > ema50[i]:
                position = {"entry": price, "idx": i}

        # SELL signaal
        elif position is not None:
            if rsi[i] > 65 and hist[i] < 0 and price < ema20[i]:
                entry = position["entry"]
                pnl   = (price / entry - 1) - 2 * fee
                trades.append({
                    "entry_idx":  position["idx"],
                    "exit_idx":   i,
                    "entry":      round(entry, 6),
                    "exit":       round(price, 6),
                    "pnl_pct":    round(pnl * 100, 4),
                    "win":        pnl > 0,
                })
                position = None

    if not trades:
        return {
            "symbol": symbol, "interval": interval, "bars": len(close),
            "trades": 0, "win_rate": 0, "profit_factor": 0,
            "max_drawdown_pct": 0, "sharpe": 0, "total_return_pct": 0,
        }

    pnls     = [t["pnl_pct"] for t in trades]
    wins     = [p for p in pnls if p > 0]
    losses   = [abs(p) for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls) * 100

    profit_factor = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else 999.0

    # Max drawdown
    equity = np.cumsum(pnls)
    peak   = np.maximum.accumulate(equity)
    dd     = peak - equity
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    # Sharpe (vereenvoudigd)
    arr    = np.array(pnls)
    sharpe = float(np.mean(arr) / np.std(arr) * np.sqrt(len(arr))) if np.std(arr) > 0 else 0.0

    return {
        "symbol":             symbol,
        "interval":           interval,
        "bars":               len(close),
        "trades":             len(trades),
        "win_rate":           round(win_rate, 2),
        "profit_factor":      round(profit_factor, 3),
        "max_drawdown_pct":   round(max_dd, 4),
        "sharpe":             round(sharpe, 3),
        "total_return_pct":   round(sum(pnls), 4),
        "trade_list":         trades[-10:],  # laatste 10 trades
    }
