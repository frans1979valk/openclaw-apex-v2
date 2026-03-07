#!/usr/bin/env python3
"""Tool: Sniper Bot beheer — instellen, opvragen en annuleren van snipers.

Gebruik:
  python3 tool_sniper.py set dip BTCUSDT [rsi=28] [max_wait=24]
  python3 tool_sniper.py set short ETHUSDT [rsi=68]
  python3 tool_sniper.py set breakout SOLUSDT
  python3 tool_sniper.py set niveau BTCUSDT target=80000 direction=dip
  python3 tool_sniper.py list
  python3 tool_sniper.py cancel <id>
  python3 tool_sniper.py reverse BTCUSDT [threshold=-5] [lookback=1,4,8,24]
"""
import sys, json
import requests

INDICATOR_URL = "http://indicator_engine:8099"


def run(action: str, *args) -> str:
    try:
        if action == "set":
            if len(args) < 2:
                return json.dumps({"error": "Gebruik: set <mode> <symbol> [opties]"})
            mode   = args[0].lower()
            symbol = args[1].upper().replace("-", "")

            # Parse extra opties: rsi=28 max_wait=12 target=80000 direction=dip
            opts = {}
            for a in args[2:]:
                if "=" in a:
                    k, v = a.split("=", 1)
                    try:
                        opts[k] = float(v)
                    except ValueError:
                        opts[k] = v

            payload = {"symbol": symbol, "mode": mode, "max_wait_hours": opts.pop("max_wait", 24)}

            if mode in ("dip", "short") and "rsi" in opts:
                payload["rsi_threshold"] = opts["rsi"]
            if mode == "niveau":
                if "target" not in opts:
                    return json.dumps({"error": "niveau mode vereist target=PRIJS"})
                payload["target_price"] = opts["target"]
                payload["direction"] = opts.get("direction", "any")
            if mode == "breakout":
                if "rsi_min" in opts: payload["rsi_min"] = opts["rsi_min"]
                if "rsi_max" in opts: payload["rsi_max"] = opts["rsi_max"]
                if "vol" in opts: payload["min_volume_ratio"] = opts["vol"]
            if "label" in opts:
                payload["label"] = str(opts["label"])

            r = requests.post(f"{INDICATOR_URL}/sniper/set",
                              json=payload, timeout=10)
            r.raise_for_status()
            data = r.json()
            s = data.get("sniper", {})
            lines = [
                f"Sniper gezet: {s.get('symbol')} {s.get('mode','').upper()} (id: {data.get('id')})",
                f"Max wachttijd: {s.get('max_wait_hours')}u",
            ]
            if s.get("rsi_threshold"):
                lines.append(f"RSI drempel: {s['rsi_threshold']}")
            if s.get("target_price"):
                lines.append(f"Doelniveau: ${s['target_price']:,.4f} ({s.get('direction','any')})")
            return json.dumps({"ok": True, "id": data.get("id"), "samenvatting": "\n".join(lines)},
                              ensure_ascii=False)

        elif action == "list":
            r = requests.get(f"{INDICATOR_URL}/sniper/list", timeout=10)
            r.raise_for_status()
            snipers = r.json()
            if not snipers:
                return json.dumps({"ok": True, "samenvatting": "Geen actieve snipers."})
            lines = [f"Actieve snipers ({len(snipers)}):"]
            for s in snipers:
                rsi_now = f"RSI nu: {s['current_rsi']:.1f}" if s.get("current_rsi") else ""
                price_now = f"${s['current_price']:,.4f}" if s.get("current_price") else ""
                thr = f"drempel {s['rsi_threshold']}" if s.get("rsi_threshold") else ""
                target = f"target ${s['target_price']:,.4f}" if s.get("target_price") else ""
                lines.append(
                    f"• [{s['id']}] {s['symbol']} {s['mode'].upper()} — "
                    f"{thr or target} | {rsi_now} | prijs {price_now} | "
                    f"wacht nog {s.get('remaining_hours',0):.1f}u"
                )
            return json.dumps({"ok": True, "count": len(snipers), "samenvatting": "\n".join(lines)},
                              ensure_ascii=False)

        elif action == "cancel":
            if not args:
                return json.dumps({"error": "Gebruik: cancel <sniper_id>"})
            sid = args[0]
            r = requests.delete(f"{INDICATOR_URL}/sniper/{sid}", timeout=10)
            r.raise_for_status()
            return json.dumps({"ok": True, "samenvatting": f"Sniper {sid} geannuleerd."})

        elif action == "reverse":
            symbol = args[0].upper().replace("-", "") if args else "BTCUSDT"
            opts = {}
            for a in args[1:]:
                if "=" in a:
                    k, v = a.split("=", 1)
                    opts[k] = v

            threshold = float(opts.get("threshold", -5.0))
            lookback_str = opts.get("lookback", "1,4,8,24")
            lookback = [int(x) for x in lookback_str.split(",")]

            payload = {
                "symbol": symbol,
                "crash_threshold_pct": threshold,
                "lookback_hours": lookback,
                "interval": opts.get("interval", "1h"),
            }
            r = requests.post(f"{INDICATOR_URL}/reverse-backtest",
                              json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()

            lines = [
                f"Reverse Backtest: {symbol} (crashes ≤ {threshold}%)",
                f"Crash events gevonden: {data.get('crash_events_found', 0)}",
                "",
                f"Beste predictor: {data.get('best_predictor', 'n/a')}",
                "",
                "Pre-crash fingerprint (signalen in ≥50% crashes):",
            ]
            for sig in data.get("combined_fingerprint", {}).get("signals", []):
                lines.append(f"  • {sig}")
            if not data.get("combined_fingerprint", {}).get("signals"):
                lines.append("  (geen consistent signaal gevonden)")

            lines.append("")
            lines.append("Volledige signaal frequenties:")
            for tb, sigs in data.get("pre_crash_signals", {}).items():
                lines.append(f"  {tb}:")
                for sig, d in sigs.items():
                    if d["frequency"] > 0:
                        lines.append(f"    {sig}: {d['frequency']*100:.0f}% ({d['count']}x)")

            return json.dumps({"ok": True, "raw": data, "samenvatting": "\n".join(lines)},
                              ensure_ascii=False, indent=2)

        else:
            return json.dumps({
                "error": f"Onbekende actie: {action}",
                "gebruik": "set|list|cancel|reverse"
            })

    except requests.exceptions.RequestException as e:
        return json.dumps({"error": f"Indicator engine niet bereikbaar: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Gebruik: tool_sniper.py <action> [args...]")
        print("  set dip BTCUSDT [rsi=28]")
        print("  set short ETHUSDT [rsi=68]")
        print("  set niveau BTCUSDT target=80000 direction=dip")
        print("  list")
        print("  cancel <id>")
        print("  reverse BTCUSDT [threshold=-5] [lookback=1,4,8,24]")
        sys.exit(1)
    result = run(*sys.argv[1:])
    data = json.loads(result)
    print(data.get("samenvatting") or json.dumps(data, indent=2, ensure_ascii=False))
