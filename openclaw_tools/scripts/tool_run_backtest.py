#!/usr/bin/env python3
"""Tool: start backtest en wacht op resultaat."""
import sys, time, logging
from tool_base import api_get, api_post, success, error

log = logging.getLogger("tool_run_backtest")

def run(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 500) -> str:
    try:
        # Start job
        job = api_post("/backtest/run", {"symbol": symbol, "interval": interval, "limit": limit, "agent": "openclaw_runtime"})
        job_id = job.get("job_id")
        log.info(f"Backtest gestart: job_id={job_id} symbol={symbol}")

        # Poll tot klaar (max 30 seconden)
        for _ in range(30):
            time.sleep(1)
            result = api_get(f"/backtest/result/{job_id}")
            if result.get("status") == "done":
                r = result.get("result", {})
                log.info(f"Backtest klaar: {symbol} trades={r.get('trades')} win={r.get('win_rate')}% pf={r.get('profit_factor')}")
                return success({"job_id": job_id, "backtest": r})
            if result.get("status") == "error":
                return error(result.get("result", {}).get("error", "onbekende fout"))

        return error("Backtest timeout na 30 seconden")
    except Exception as e:
        log.error(f"tool_run_backtest fout: {e}")
        return error(str(e))

if __name__ == "__main__":
    symbol   = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    interval = sys.argv[2] if len(sys.argv) > 2 else "1h"
    print(run(symbol, interval))
