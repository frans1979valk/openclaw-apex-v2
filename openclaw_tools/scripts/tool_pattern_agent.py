#!/usr/bin/env python3
"""Tool: roep kimi_pattern_agent aan voor patroonanalyse, OHLCV collectie en rapporten."""
import sys, json, logging
import requests

log = logging.getLogger("tool_pattern_agent")

PATTERN_URL = "http://kimi_pattern_agent:8098"


def run(action: str, *args) -> str:
    try:
        if action == "status":
            r = requests.get(f"{PATTERN_URL}/health", timeout=10)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "collect":
            r = requests.post(f"{PATTERN_URL}/collect", timeout=120)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "analyze":
            r = requests.post(f"{PATTERN_URL}/analyze", timeout=120)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "report":
            date = args[0] if len(args) > 0 else "latest"
            if date == "latest":
                r = requests.get(f"{PATTERN_URL}/report/latest", timeout=10)
            else:
                r = requests.get(f"{PATTERN_URL}/report/{date}", timeout=10)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "ohlcv":
            r = requests.get(f"{PATTERN_URL}/ohlcv/status", timeout=10)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "stats":
            r = requests.get(f"{PATTERN_URL}/stats", timeout=10)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        else:
            return json.dumps({"ok": False, "error": f"Onbekende actie: {action}",
                               "beschikbaar": ["status", "collect", "analyze", "report [datum]", "ohlcv", "stats"]}, indent=2)

    except requests.RequestException as e:
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Gebruik: python3 tool_pattern_agent.py <actie> [args]",
            "acties": {
                "status": "Health check + scheduled jobs",
                "collect": "Handmatig OHLCV data ophalen",
                "analyze": "Handmatig Kimi analyse starten",
                "report": "Laatste rapport ophalen (of: report 2026-03-06)",
                "ohlcv": "Overzicht opgeslagen OHLCV data",
                "stats": "Signaal performance statistieken",
            }
        }, indent=2))
        sys.exit(1)
    print(run(sys.argv[1], *sys.argv[2:]))
