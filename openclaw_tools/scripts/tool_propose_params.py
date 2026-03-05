#!/usr/bin/env python3
"""Tool: dien een parametervoorstel in bij de control_api."""
import sys, json, logging
from tool_base import api_post, success, error

log = logging.getLogger("tool_propose_params")

# Absolute grenzen — nooit overschrijden
PARAM_BOUNDS = {
    "rsi_buy_threshold":  (20,  40),
    "rsi_sell_threshold": (60,  80),
    "stoploss_pct":       (1.5, 6.0),
    "takeprofit_pct":     (3.0, 12.0),
    "position_size_base": (1,   5),
}

def clamp(key: str, val) -> float:
    lo, hi = PARAM_BOUNDS[key]
    return max(lo, min(hi, float(val)))

def run(params: dict, reden: str = "OpenClaw agent voorstel", agent: str = "openclaw_runtime") -> str:
    try:
        # Valideer en clamp
        valid = {k: clamp(k, v) for k, v in params.items() if k in PARAM_BOUNDS}
        if not valid:
            return error(f"Geen geldige parameters. Toegestaan: {list(PARAM_BOUNDS.keys())}")

        resp = api_post("/config/propose", {"agent": agent, "params": valid, "reason": reden})
        pid  = resp.get("proposal_id")
        log.info(f"Voorstel #{pid} ingediend: {valid} — {reden}")
        return success({"proposal_id": pid, "params": valid, "reason": reden})
    except Exception as e:
        log.error(f"tool_propose_params fout: {e}")
        return error(str(e))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(error("Gebruik: tool_propose_params.py '{\"rsi_buy_threshold\": 32}' 'reden'"))
    else:
        params = json.loads(sys.argv[1])
        reden  = sys.argv[2] if len(sys.argv) > 2 else "Agent voorstel"
        print(run(params, reden))
