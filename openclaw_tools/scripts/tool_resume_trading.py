#!/usr/bin/env python3
"""Tool: hervat trading na pauze."""
import logging
from tool_base import api_post, success, error

log = logging.getLogger("tool_resume_trading")

def run() -> str:
    try:
        resp = api_post("/trading/resume", {})
        log.info("Trading hervat door OpenClaw agent")
        return success({"resumed": True, "response": resp})
    except Exception as e:
        log.error(f"tool_resume_trading fout: {e}")
        return error(str(e))

if __name__ == "__main__":
    print(run())
