#!/usr/bin/env python3
"""Tool: roep indicator_engine aan voor historische signalen, indicators en patronen."""
import sys, json, logging
import requests

log = logging.getLogger("tool_intelligence")

INDICATOR_URL = "http://indicator_engine:8099"


def run(action: str, *args) -> str:
    try:
        if action == "signal":
            symbol = args[0] if len(args) > 0 else "BTCUSDT"
            r = requests.get(f"{INDICATOR_URL}/signal/{symbol}", timeout=15)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "indicators":
            symbol = args[0] if len(args) > 0 else "BTCUSDT"
            r = requests.get(f"{INDICATOR_URL}/indicators/{symbol}", timeout=15)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "patterns":
            symbol = args[0] if len(args) > 0 else "BTCUSDT"
            r = requests.get(f"{INDICATOR_URL}/patterns/{symbol}", timeout=15)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "coverage":
            r = requests.get(f"{INDICATOR_URL}/coverage", timeout=15)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "import":
            symbol = args[0] if len(args) > 0 else None
            payload = {"symbol": symbol} if symbol else {}
            r = requests.post(f"{INDICATOR_URL}/import", json=payload, timeout=30)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        elif action == "health":
            r = requests.get(f"{INDICATOR_URL}/health", timeout=5)
            r.raise_for_status()
            return json.dumps({"ok": True, **r.json()}, ensure_ascii=False, indent=2)

        else:
            return json.dumps({
                "ok": False,
                "error": f"Onbekende actie: {action}. Gebruik: signal, indicators, patterns, coverage, import, health"
            }, indent=2)

    except requests.RequestException as e:
        log.error(f"Intelligence request fout: {e}")
        return json.dumps({"ok": False, "error": str(e)}, indent=2)
    except Exception as e:
        log.error(f"tool_intelligence fout: {e}")
        return json.dumps({"ok": False, "error": str(e)}, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "error": "Gebruik: python3 tool_intelligence.py <actie> [args...]",
            "acties": {
                "signal <SYMBOL>": "Historisch signaal + win rate + recente patronen",
                "indicators <SYMBOL>": "Huidige TA indicators (RSI, MACD, BB, EMA, ADX, ATR)",
                "patterns <SYMBOL>": "Patroon-precedenten met historisch resultaat",
                "coverage": "Databeschikbaarheid per coin",
                "import [SYMBOL]": "Start historische data import (achtergrond)",
                "health": "Service status",
            },
            "voorbeelden": [
                "python3 tool_intelligence.py signal AAVEUSDT",
                "python3 tool_intelligence.py indicators BTCUSDT",
                "python3 tool_intelligence.py patterns ETHUSDT",
                "python3 tool_intelligence.py coverage",
                "python3 tool_intelligence.py import SOLUSDT",
            ]
        }, indent=2))
        sys.exit(1)
    print(run(sys.argv[1], *sys.argv[2:]))
