"""
setup_judge — realtime decision layer op basis van historische signal_context data.

Geen AI-calls. Raadpleegt apex.db direct.

CLI aanroep:
  python3 setup_judge.py --symbol BTCUSDT --signal BUY --rsi 32.5 --macd bullish --adx 28

Python import:
  from setup_judge import judge
  result = judge("BTCUSDT", "BUY", rsi=32.5, macd="bullish", adx=28.0)
  print(result["verdict"])  # SKIP / TWIJFEL / TOESTAAN

Retourneert dict met:
  verdict     : SKIP / TWIJFEL / TOESTAAN / ONBEKEND
  confidence  : laag / midden / hoog  (op basis van n)
  n           : aantal historische trades in deze setup
  avg_1h      : gemiddelde PnL 1h
  avg_4h      : gemiddelde PnL 4h
  win_pct_1h  : win percentage 1h
  reden       : leesbare uitleg
  coin_verdict: coin-specifiek oordeel (indien genoeg data)
"""
import sqlite3
import argparse
import json
import os

DB_PATH = os.getenv("APEX_DB", "/var/apex/apex.db")

# ── Drempels (zelfde als signal_analyzer.py) ─────────────────────────────────
SKIP_WIN_PCT   = 25.0
ALLOW_WIN_PCT  = 40.0
SKIP_PNL_1H    = -0.30
ALLOW_PNL_1H   =  0.00

MIN_N_VERDICT  = 5    # min. trades voor een oordeel
MIN_N_COIN     = 5    # min. trades voor coin-specifiek oordeel

# Confidence op basis van n
CONFIDENCE_HIGH   = 20
CONFIDENCE_MEDIUM = 8


def _rsi_zone(rsi):
    if rsi is None:
        return None
    if rsi < 35:
        return "oversold"
    if rsi < 50:
        return "mid-low"
    if rsi < 65:
        return "mid-high"
    return "overbought"


def _adx_strong(adx):
    """1 als trending (adx >= 25), 0 als ranging."""
    if adx is None:
        return None
    return 1 if adx >= 25 else 0


def _confidence(n):
    if n >= CONFIDENCE_HIGH:
        return "hoog"
    if n >= CONFIDENCE_MEDIUM:
        return "midden"
    return "laag"


def _verdict(win_pct, avg_1h, n):
    if n < MIN_N_VERDICT:
        return "ONBEKEND"
    skip_v = allow_v = 0
    if win_pct is not None:
        if float(win_pct) < SKIP_WIN_PCT:
            skip_v += 1
        elif float(win_pct) >= ALLOW_WIN_PCT:
            allow_v += 1
    if avg_1h is not None:
        if float(avg_1h) < SKIP_PNL_1H:
            skip_v += 1
        elif float(avg_1h) >= ALLOW_PNL_1H:
            allow_v += 1
    if skip_v >= 2:
        return "SKIP"
    if allow_v >= 2:
        return "TOESTAAN"
    return "TWIJFEL"


def judge(symbol: str, signal: str, rsi: float = None,
          macd: str = None, adx: float = None) -> dict:
    """
    Geeft een verdict terug voor de gegeven setup.
    Kijkt op 3 niveaus: generiek → coin-specifiek → combinatie.
    """
    con = sqlite3.connect(DB_PATH)

    rsi_zone  = _rsi_zone(rsi)
    adx_str   = _adx_strong(adx)
    sym       = symbol.upper()
    sig       = signal.upper()
    macd_norm = macd.lower() if macd else None

    results = {}

    # ── Niveau 1: Generieke setup (signaal + RSI + MACD + ADX) ──────────────
    if rsi_zone and macd_norm and adx_str is not None:
        row = con.execute("""
            SELECT COUNT(*) as n,
                ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
                ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
                ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
            FROM signal_context sc
            JOIN signal_performance sp ON sp.id = sc.signal_perf_id
            WHERE sp.pnl_1h_pct IS NOT NULL
              AND sc.signal = ?
              AND CASE WHEN sc.rsi_1h<35 THEN 'oversold'
                       WHEN sc.rsi_1h<50 THEN 'mid-low'
                       WHEN sc.rsi_1h<65 THEN 'mid-high'
                       ELSE 'overbought' END = ?
              AND sc.macd_signal = ?
              AND sc.adx_strong = ?
        """, (sig, rsi_zone, macd_norm, adx_str)).fetchone()
        if row and row[0] >= MIN_N_VERDICT:
            n, avg_1h, avg_4h, win1h = row
            results["generiek"] = {
                "n": n, "avg_1h": avg_1h, "avg_4h": avg_4h,
                "win_pct_1h": win1h,
                "verdict": _verdict(win1h, avg_1h, n),
                "confidence": _confidence(n),
            }

    # ── Niveau 2: Coin-specifiek (signaal + RSI-zone) ────────────────────────
    if rsi_zone:
        row = con.execute("""
            SELECT COUNT(*) as n,
                ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
                ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
                ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
            FROM signal_context sc
            JOIN signal_performance sp ON sp.id = sc.signal_perf_id
            WHERE sp.pnl_1h_pct IS NOT NULL
              AND sc.symbol = ?
              AND sc.signal = ?
              AND CASE WHEN sc.rsi_1h<35 THEN 'oversold'
                       WHEN sc.rsi_1h<50 THEN 'mid-low'
                       WHEN sc.rsi_1h<65 THEN 'mid-high'
                       ELSE 'overbought' END = ?
        """, (sym, sig, rsi_zone)).fetchone()
        if row and row[0] >= MIN_N_COIN:
            n, avg_1h, avg_4h, win1h = row
            results["coin_rsi"] = {
                "n": n, "avg_1h": avg_1h, "avg_4h": avg_4h,
                "win_pct_1h": win1h,
                "verdict": _verdict(win1h, avg_1h, n),
                "confidence": _confidence(n),
            }

    # ── Niveau 3: Alleen coin (fallback als weinig data) ─────────────────────
    row = con.execute("""
        SELECT COUNT(*) as n,
            ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
        FROM signal_context sc
        JOIN signal_performance sp ON sp.id = sc.signal_perf_id
        WHERE sp.pnl_1h_pct IS NOT NULL
          AND sc.symbol = ?
    """, (sym,)).fetchone()
    if row and row[0] >= MIN_N_COIN:
        n, avg_1h, avg_4h, win1h = row
        results["coin_algemeen"] = {
            "n": n, "avg_1h": avg_1h, "avg_4h": avg_4h,
            "win_pct_1h": win1h,
            "verdict": _verdict(win1h, avg_1h, n),
            "confidence": _confidence(n),
        }

    con.close()

    # ── Bepaal eindvonnis ────────────────────────────────────────────────────
    # Prioriteit: generiek (meest specifiek) > coin_rsi > coin_algemeen
    # Bij conflict: meest specifieke wint, maar meldt het conflict
    primary_key   = next((k for k in ["generiek","coin_rsi","coin_algemeen"] if k in results), None)
    final_verdict = results[primary_key]["verdict"] if primary_key else "ONBEKEND"
    final_data    = results[primary_key] if primary_key else {}

    # Conflict check
    verdicts = {k: v["verdict"] for k, v in results.items() if v["verdict"] != "ONBEKEND"}
    conflict = len(set(verdicts.values())) > 1

    reden_parts = []
    if "generiek" in results:
        g = results["generiek"]
        reden_parts.append(
            f"Setup [{sig}+{rsi_zone}+MACD:{macd_norm}+ADX:{'trend' if adx_str else 'range'}]: "
            f"n={g['n']}, avg_1h={g['avg_1h']}%, win%={g['win_pct_1h']} → {g['verdict']}"
        )
    if "coin_rsi" in results:
        c = results["coin_rsi"]
        reden_parts.append(
            f"{sym} specifiek [{sig}+{rsi_zone}]: "
            f"n={c['n']}, avg_1h={c['avg_1h']}%, win%={c['win_pct_1h']} → {c['verdict']}"
        )
    if "coin_algemeen" in results:
        ca = results["coin_algemeen"]
        reden_parts.append(
            f"{sym} algemeen: n={ca['n']}, avg_1h={ca['avg_1h']}%, win%={ca['win_pct_1h']} → {ca['verdict']}"
        )
    if not reden_parts:
        reden_parts.append("Onvoldoende historische data voor dit symbool/setup.")

    if conflict:
        reden_parts.append("⚠️  Niveaus conflicteren — meest specifieke wint.")

    return {
        "symbol":       sym,
        "signal":       sig,
        "rsi":          rsi,
        "rsi_zone":     rsi_zone,
        "macd":         macd_norm,
        "adx":          adx,
        "adx_strong":   adx_str,
        "verdict":      final_verdict,
        "confidence":   final_data.get("confidence", "laag"),
        "n":            final_data.get("n", 0),
        "avg_1h":       final_data.get("avg_1h"),
        "avg_4h":       final_data.get("avg_4h"),
        "win_pct_1h":   final_data.get("win_pct_1h"),
        "conflict":     conflict,
        "levels":       results,
        "reden":        " | ".join(reden_parts),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup judge — SKIP/TWIJFEL/TOESTAAN")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--signal", required=True)
    parser.add_argument("--rsi",    type=float, default=None)
    parser.add_argument("--macd",   default=None, choices=["bullish","bearish"])
    parser.add_argument("--adx",    type=float, default=None)
    parser.add_argument("--json",   action="store_true", help="Output als JSON")
    args = parser.parse_args()

    result = judge(args.symbol, args.signal, args.rsi, args.macd, args.adx)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        label = {"SKIP": "❌ SKIP", "TWIJFEL": "⚠️  TWIJFEL",
                 "TOESTAAN": "✅ TOESTAAN", "ONBEKEND": "❓ ONBEKEND"}
        print(f"\n{'='*55}")
        print(f"  {args.symbol} | {args.signal}")
        print(f"  RSI: {args.rsi} ({result['rsi_zone']})  MACD: {args.macd}  ADX: {args.adx}")
        print(f"{'='*55}")
        print(f"  Verdict    : {label.get(result['verdict'], result['verdict'])}")
        print(f"  Confidence : {result['confidence']}  (n={result['n']})")
        if result['avg_1h'] is not None:
            print(f"  Avg 1h PnL : {result['avg_1h']}%")
        if result['avg_4h'] is not None:
            print(f"  Avg 4h PnL : {result['avg_4h']}%")
        if result['win_pct_1h'] is not None:
            print(f"  Win% 1h    : {result['win_pct_1h']}%")
        print(f"\n  Onderbouwing:")
        for r in result['reden'].split(" | "):
            print(f"    {r}")
        print()
