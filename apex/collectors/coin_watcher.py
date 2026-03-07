#!/usr/bin/env python3
"""coin_watcher — detecteert nieuwe coins en triggert automatisch data-import.

Gebruik:
  python3 coin_watcher.py              # check + auto-import nieuwe coins
  python3 coin_watcher.py --status     # toon huidige coverage
  python3 coin_watcher.py --enrich     # trigger historical enrichment
  python3 coin_watcher.py --force BTC  # forceer import voor specifieke coin

De indicator_engine voert dit ook automatisch uit elke 30 minuten.
"""
import sys, json, argparse
import requests

INDICATOR_URL = "http://indicator_engine:8099"


def get_status() -> dict:
    r = requests.get(f"{INDICATOR_URL}/coin-watcher/status", timeout=15)
    r.raise_for_status()
    return r.json()


def get_enrich_status() -> dict:
    r = requests.get(f"{INDICATOR_URL}/historical-enrich/status", timeout=15)
    r.raise_for_status()
    return r.json()


def trigger_enrich() -> dict:
    r = requests.post(f"{INDICATOR_URL}/historical-enrich", timeout=15)
    r.raise_for_status()
    return r.json()


def trigger_import(symbol: str, months: int = 48) -> dict:
    r = requests.post(f"{INDICATOR_URL}/import",
                      json={"symbols": [symbol], "months": months},
                      timeout=30)
    r.raise_for_status()
    return r.json()


def run(args):
    if args.status:
        status = get_status()
        enrich = get_enrich_status()
        print(f"\nCoin Coverage:")
        print(f"  Actief (48u):   {len(status.get('active_coins', []))} coins")
        print(f"  Gedekt:         {len(status.get('covered_coins', []))} coins")
        missing = status.get("missing_coverage", [])
        if missing:
            print(f"  Ontbrekend ({len(missing)}): {', '.join(missing)}")
        else:
            print("  Ontbrekend:     geen")
        print(f"\nHistorical Context:")
        print(f"  Verrijkt:       {enrich.get('enriched', 0)}/{enrich.get('total_backtest', 0)} "
              f"({enrich.get('coverage_pct', 0)}%)")
        print(f"  Coins:          {enrich.get('coins', 0)}")
        print(f"  Periode:        {enrich.get('date_range', {}).get('from', '?')[:10]} → "
              f"{enrich.get('date_range', {}).get('to', '?')[:10]}")
        if enrich.get("running"):
            print("  Status:         bezig...")
        return

    if args.enrich:
        result = trigger_enrich()
        print(f"Historical enrichment: {result.get('message', result)}")
        return

    if args.force:
        symbol = args.force.upper().replace("-", "") + ("USDT" if not args.force.upper().endswith("USDT") else "")
        print(f"Import starten voor {symbol} (48 maanden)...")
        result = trigger_import(symbol)
        print(f"Import: {result}")
        print("Enrichment triggeren...")
        trigger_enrich()
        print("Klaar. Enrichment loopt in achtergrond.")
        return

    # Standaard: check en auto-import
    status = get_status()
    missing = status.get("missing_coverage", [])

    if not missing:
        print("Alle actieve coins hebben indicator coverage. Niets te doen.")
        enrich = get_enrich_status()
        print(f"Historical context: {enrich.get('enriched', 0)}/{enrich.get('total_backtest', 0)} verrijkt "
              f"({enrich.get('coverage_pct', 0)}%)")
        return

    print(f"{len(missing)} nieuwe coin(s) gevonden: {', '.join(missing)}")
    for coin in missing:
        print(f"  Import starten voor {coin}...")
        try:
            trigger_import(coin)
            print(f"  {coin}: import gestart")
        except Exception as e:
            print(f"  {coin}: fout — {e}")

    print("Historical enrichment triggeren...")
    trigger_enrich()
    print("Klaar. Import + enrichment lopen in achtergrond.")


def main():
    parser = argparse.ArgumentParser(description="Coin watcher — auto-import nieuwe coins")
    parser.add_argument("--status", action="store_true", help="Toon huidige coverage")
    parser.add_argument("--enrich", action="store_true", help="Trigger historical enrichment")
    parser.add_argument("--force", metavar="COIN", help="Forceer import voor specifieke coin (bijv. BTC)")
    args = parser.parse_args()
    try:
        run(args)
    except requests.exceptions.ConnectionError:
        print("Fout: indicator_engine niet bereikbaar op", INDICATOR_URL)
        sys.exit(1)
    except Exception as e:
        print(f"Fout: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
