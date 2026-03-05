#!/usr/bin/env python3
"""Tool: haal recente marktgebeurtenissen op uit de database."""
import sys, logging
from tool_base import api_get, success, error

log = logging.getLogger("tool_fetch_news")

def run(hours: int = 24, symbol: str = "") -> str:
    try:
        params = {"hours": hours}
        if symbol:
            params["symbol"] = symbol.upper()
        events = api_get("/history/events", params)
        items  = events.get("events", [])
        log.info(f"Nieuws opgehaald: {len(items)} events (laatste {hours}u)")
        return success({"events": items[:20], "total": len(items), "hours": hours})
    except Exception as e:
        log.error(f"tool_fetch_news fout: {e}")
        return error(str(e))

if __name__ == "__main__":
    hours  = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    symbol = sys.argv[2] if len(sys.argv) > 2 else ""
    print(run(hours, symbol))
