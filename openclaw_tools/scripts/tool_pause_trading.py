#!/usr/bin/env python3
"""Tool: pauzeer trading voor N minuten."""
import sys, logging
from tool_base import api_post, success, error

log = logging.getLogger("tool_pause_trading")

def run(minutes: int = 30, reason: str = "OpenClaw risk agent pauze") -> str:
    try:
        resp = api_post("/trading/pause", {"minutes": minutes, "reason": reason})
        log.info(f"Trading gepauzeerd voor {minutes} min — {reason}")
        return success({"paused": True, "minutes": minutes, "until": resp.get("paused_until")})
    except Exception as e:
        log.error(f"tool_pause_trading fout: {e}")
        return error(str(e))

if __name__ == "__main__":
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    reason  = sys.argv[2] if len(sys.argv) > 2 else "Risk agent pauze"
    print(run(minutes, reason))
