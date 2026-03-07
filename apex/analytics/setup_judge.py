"""
setup_judge — realtime decision layer op basis van historical_context (PostgreSQL).

Primaire data: historical_context (31k+ records, 2022-2026, via jojo_analytics)
Recente correctie: signal_context (SQLite, laatste weken, optioneel)

Geen AI-calls.

CLI aanroep:
  python3 setup_judge.py --symbol BTCUSDT --signal BUY --rsi 32.5 --macd bullish --adx 28

Python import:
  from setup_judge import judge
  result = judge("BTCUSDT", "BUY", rsi=32.5, macd="bullish", adx=28.0)
  print(result["verdict"])  # SKIP / TWIJFEL / TOESTAAN / ONBEKEND

Retourneert dict met:
  verdict     : SKIP / TWIJFEL / TOESTAAN / ONBEKEND
  confidence  : laag / midden / hoog  (op basis van n)
  n           : aantal historische trades in deze setup
  avg_1h      : gemiddelde PnL 1h
  avg_4h      : gemiddelde PnL 4h
  win_pct_1h  : win percentage 1h
  reden       : leesbare uitleg
  levels      : detail per niveau
"""
import sqlite3
import argparse
import json
import os

import requests

ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://jojo_analytics:8097")
DB_PATH       = os.getenv("APEX_DB", "/var/apex/apex.db")

# ── Drempels ──────────────────────────────────────────────────────────────────
SKIP_WIN_PCT   = 25.0
ALLOW_WIN_PCT  = 40.0
SKIP_PNL_1H    = -0.30
ALLOW_PNL_1H   =  0.00

MIN_N_VERDICT  = 10   # min. trades voor een oordeel (ruimer vanwege grotere dataset)
MIN_N_COIN     = 5    # min. trades voor coin-specifiek oordeel

CONFIDENCE_HIGH   = 50
CONFIDENCE_MEDIUM = 20


def _query(sql: str) -> list:
    """Voert een SELECT uit via jojo_analytics /query. Retourneert lijst van rijen."""
    try:
        r = requests.post(f"{ANALYTICS_URL}/query", json={"sql": sql}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("rows", [])
    except Exception:
        return []


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


def _hctx_aggregate(where_clause: str) -> tuple:
    """Haalt n/avg_1h/avg_4h/win1h op uit historical_context met gegeven WHERE."""
    rows = _query(f"""
        SELECT COUNT(*) as n,
            ROUND(AVG(pnl_1h_pct)::numeric, 3) as avg_1h,
            ROUND(AVG(pnl_4h_pct)::numeric, 3) as avg_4h,
            ROUND(100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)::numeric
                  / NULLIF(COUNT(*), 0), 1) as win1h
        FROM historical_context
        WHERE pnl_1h_pct IS NOT NULL
          AND symbol != 'USDCUSDT'
          AND {where_clause}
    """)
    return rows[0] if rows else None


def _parse_row(row) -> dict:
    """Converteert query-rij naar dict met n/avg_1h/avg_4h/win_pct_1h."""
    if not row or row[0] is None:
        return None
    n = int(row[0])
    avg_1h = float(row[1]) if row[1] is not None else None
    avg_4h = float(row[2]) if row[2] is not None else None
    win1h  = float(row[3]) if row[3] is not None else None
    return {"n": n, "avg_1h": avg_1h, "avg_4h": avg_4h, "win_pct_1h": win1h}


def _signal_ctx_recency(sym: str, sig: str) -> dict:
    """Optioneel: recente data uit signal_context (SQLite) als correctielaag."""
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("""
            SELECT COUNT(*) as n,
                ROUND(AVG(sp.pnl_1h_pct), 3) as avg_1h,
                ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*), 1) as win1h
            FROM signal_context sc
            JOIN signal_performance sp ON sp.id = sc.signal_perf_id
            WHERE sp.pnl_1h_pct IS NOT NULL
              AND sc.symbol = ?
              AND sc.signal = ?
        """, (sym, sig)).fetchone()
        con.close()
        if row and row[0] >= 5:
            return {"n": int(row[0]), "avg_1h": row[1], "win_pct_1h": row[2]}
    except Exception:
        pass
    return None


def judge(symbol: str, signal: str, rsi: float = None,
          macd: str = None, adx: float = None) -> dict:
    """
    Geeft een verdict terug voor de gegeven setup.
    Primair: historical_context (PostgreSQL, 31k+ records, 2022-2026)
    Supplemental: signal_context (SQLite, recente weken, optioneel)
    """
    rsi_zone  = _rsi_zone(rsi)
    sym       = symbol.upper()
    sig       = signal.upper()
    macd_norm = macd.lower() if macd else None
    adx_trend = (adx >= 25) if adx is not None else None

    results = {}

    # ── Niveau 1: Generieke setup (signal + rsi_zone + macd_richting + adx) ──
    if rsi_zone and macd_norm and adx_trend is not None:
        macd_clause = "(macd_hist > 0)" if macd_norm == "bullish" else "(macd_hist <= 0)"
        adx_clause  = "(adx > 25)" if adx_trend else "(adx <= 25)"
        row = _hctx_aggregate(
            f"signal = '{sig}' AND rsi_zone = '{rsi_zone}' "
            f"AND {macd_clause} AND {adx_clause}"
        )
        parsed = _parse_row(row)
        if parsed and parsed["n"] >= MIN_N_VERDICT:
            parsed["verdict"]    = _verdict(parsed["win_pct_1h"], parsed["avg_1h"], parsed["n"])
            parsed["confidence"] = _confidence(parsed["n"])
            parsed["bron"]       = "historical_context"
            results["generiek"]  = parsed

    # ── Niveau 2: Coin-specifiek (symbol + signal + rsi_zone) ─────────────────
    if rsi_zone:
        row = _hctx_aggregate(
            f"symbol = '{sym}' AND signal = '{sig}' AND rsi_zone = '{rsi_zone}'"
        )
        parsed = _parse_row(row)
        if parsed and parsed["n"] >= MIN_N_COIN:
            parsed["verdict"]    = _verdict(parsed["win_pct_1h"], parsed["avg_1h"], parsed["n"])
            parsed["confidence"] = _confidence(parsed["n"])
            parsed["bron"]       = "historical_context"
            results["coin_rsi"]  = parsed

    # ── Niveau 3: Coin-algemeen (symbol + signal) ─────────────────────────────
    row = _hctx_aggregate(f"symbol = '{sym}' AND signal = '{sig}'")
    parsed = _parse_row(row)
    if parsed and parsed["n"] >= MIN_N_COIN:
        parsed["verdict"]       = _verdict(parsed["win_pct_1h"], parsed["avg_1h"], parsed["n"])
        parsed["confidence"]    = _confidence(parsed["n"])
        parsed["bron"]          = "historical_context"
        results["coin_algemeen"] = parsed

    # ── Recente correctielaag (signal_context, optioneel) ─────────────────────
    recency = _signal_ctx_recency(sym, sig)
    if recency:
        results["recency"] = recency

    # ── Eindvonnis ────────────────────────────────────────────────────────────
    primary_key   = next((k for k in ["generiek", "coin_rsi", "coin_algemeen"] if k in results), None)
    final_verdict = results[primary_key]["verdict"] if primary_key else "ONBEKEND"
    final_data    = results[primary_key] if primary_key else {}

    verdicts = {k: v["verdict"] for k, v in results.items()
                if k != "recency" and v.get("verdict") != "ONBEKEND"}
    conflict = len(set(verdicts.values())) > 1

    reden_parts = []
    if "generiek" in results:
        g = results["generiek"]
        adx_label = "trend" if adx_trend else "range"
        reden_parts.append(
            f"Setup [{sig}+{rsi_zone}+MACD:{macd_norm}+ADX:{adx_label}]: "
            f"n={g['n']}, avg_1h={g['avg_1h']}%, win%={g['win_pct_1h']} → {g['verdict']}"
        )
    if "coin_rsi" in results:
        c = results["coin_rsi"]
        reden_parts.append(
            f"{sym} [{sig}+{rsi_zone}]: "
            f"n={c['n']}, avg_1h={c['avg_1h']}%, win%={c['win_pct_1h']} → {c['verdict']}"
        )
    if "coin_algemeen" in results:
        ca = results["coin_algemeen"]
        reden_parts.append(
            f"{sym} algemeen [{sig}]: "
            f"n={ca['n']}, avg_1h={ca['avg_1h']}%, win%={ca['win_pct_1h']} → {ca['verdict']}"
        )
    if recency:
        reden_parts.append(
            f"Recente data ({recency['n']} trades): "
            f"avg_1h={recency['avg_1h']}%, win%={recency['win_pct_1h']}"
        )
    if not reden_parts:
        reden_parts.append("Onvoldoende historische data voor dit symbool/setup.")
    if conflict:
        reden_parts.append("⚠️  Niveaus conflicteren — meest specifieke wint.")

    return {
        "symbol":     sym,
        "signal":     sig,
        "rsi":        rsi,
        "rsi_zone":   rsi_zone,
        "macd":       macd_norm,
        "adx":        adx,
        "adx_strong": adx_trend,
        "verdict":    final_verdict,
        "confidence": final_data.get("confidence", "laag"),
        "n":          final_data.get("n", 0),
        "avg_1h":     final_data.get("avg_1h"),
        "avg_4h":     final_data.get("avg_4h"),
        "win_pct_1h": final_data.get("win_pct_1h"),
        "conflict":   conflict,
        "levels":     results,
        "reden":      " | ".join(reden_parts),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup judge — SKIP/TWIJFEL/TOESTAAN")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--signal", required=True)
    parser.add_argument("--rsi",    type=float, default=None)
    parser.add_argument("--macd",   default=None, choices=["bullish", "bearish"])
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
        if result["avg_1h"] is not None:
            print(f"  Avg 1h PnL : {result['avg_1h']}%")
        if result["avg_4h"] is not None:
            print(f"  Avg 4h PnL : {result['avg_4h']}%")
        if result["win_pct_1h"] is not None:
            print(f"  Win% 1h    : {result['win_pct_1h']}%")
        print(f"\n  Onderbouwing:")
        for r in result["reden"].split(" | "):
            print(f"    {r}")
        print()
