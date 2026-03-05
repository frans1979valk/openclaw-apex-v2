#!/usr/bin/env python3
"""Tool: roep jojo_analytics service aan voor indicators, DB queries en Market Oracle."""
import sys, json, logging
import requests

log = logging.getLogger("tool_analytics")

ANALYTICS_URL = "http://jojo_analytics:8097"


def run(action: str, *args) -> str:
    try:
        if action == "indicators":
            symbol = args[0] if len(args) > 0 else "BTCUSDT"
            interval = args[1] if len(args) > 1 else "1h"
            limit = int(args[2]) if len(args) > 2 else 200
            r = requests.post(f"{ANALYTICS_URL}/indicators",
                              json={"symbol": symbol, "interval": interval, "limit": limit},
                              timeout=15)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "query":
            sql = args[0] if len(args) > 0 else ""
            if not sql:
                return json.dumps({"ok": False, "error": "SQL query vereist"}, indent=2)
            r = requests.post(f"{ANALYTICS_URL}/query",
                              json={"sql": sql},
                              timeout=15)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "oracle":
            sub_action = args[0] if len(args) > 0 else "scan"
            text = args[1] if len(args) > 1 else ""
            r = requests.post(f"{ANALYTICS_URL}/oracle",
                              json={"action": sub_action, "text": text},
                              timeout=30)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        else:
            return json.dumps({"ok": False, "error": f"Onbekende actie: {action}. Gebruik: indicators, query, oracle"}, indent=2)

    except requests.RequestException as e:
        log.error(f"Analytics request fout: {e}")
        return json.dumps({"ok": False, "error": str(e)}, indent=2)
    except Exception as e:
        log.error(f"tool_analytics fout: {e}")
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Gebruik: python3 tool_analytics.py <indicators|query|oracle> [args...]",
            "voorbeelden": [
                "python3 tool_analytics.py indicators AAVEUSDT 1h",
                "python3 tool_analytics.py query \"SELECT symbol, COUNT(*) FROM signal_performance GROUP BY symbol\"",
                "python3 tool_analytics.py oracle scan",
                "python3 tool_analytics.py oracle event \"Fed verhoogt rente\"",
            ]
        }, indent=2))
        sys.exit(1)
    print(run(sys.argv[1], *sys.argv[2:]))
