#!/usr/bin/env python3
"""Tool: pas een voorstel toe (alleen als confirm policy het toestaat)."""
import sys, logging
from tool_base import api_get, api_post, success, error

log = logging.getLogger("tool_apply_proposal")

def run(proposal_id: int) -> str:
    try:
        # Check confirm policy
        policy = api_get("/policy/confirm")
        if policy.get("confirm_required"):
            log.warning(f"Voorstel #{proposal_id} NIET toegepast — confirm_required=true (Telegram vereist)")
            return success({
                "applied": False,
                "reason": "confirm_required=true — stuur /ok " + str(proposal_id) + " via Telegram om te bevestigen",
                "proposal_id": proposal_id,
            })

        resp = api_post(f"/proposals/{proposal_id}/apply", {})
        log.info(f"Voorstel #{proposal_id} toegepast")
        return success({"applied": True, "proposal_id": proposal_id, "response": resp})
    except Exception as e:
        log.error(f"tool_apply_proposal fout: {e}")
        return error(str(e))

if __name__ == "__main__":
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if not pid:
        print(error("Gebruik: tool_apply_proposal.py <proposal_id>"))
    else:
        print(run(pid))
