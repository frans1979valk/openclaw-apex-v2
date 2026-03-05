#!/usr/bin/env python3
"""Tool: haal platform status op (health + actuele marktdata)."""
import sys, logging
from tool_base import api_get, success, error

log = logging.getLogger("tool_status")

def run() -> str:
    try:
        health  = api_get("/health")
        state   = api_get("/state/latest")
        metrics = api_get("/metrics/performance")
        trading = api_get("/trading/status")

        coins = state.get("coins", [])
        coin_summary = [
            {
                "symbol":   c.get("symbol"),
                "signal":   c.get("signal"),
                "price":    c.get("price"),
                "rsi":      round(c.get("rsi") or 0, 1),
                "change":   round(c.get("change_pct") or 0, 2),
                "tf_bias":  c.get("tf_bias"),
            }
            for c in coins
        ]
        result = {
            "health":   health,
            "trading":  trading,
            "coins":    coin_summary,
            "overall_win_rate": metrics.get("overall", {}).get("win_rate_pct"),
            "crash_max_24h": metrics.get("crash_24h", {}).get("max_score"),
            "ts":       state.get("ts"),
        }
        log.info(f"Status opgehaald: {len(coins)} coins, win_rate={result['overall_win_rate']}%")
        return success(result)
    except Exception as e:
        log.error(f"tool_status fout: {e}")
        return error(str(e))

if __name__ == "__main__":
    print(run())
