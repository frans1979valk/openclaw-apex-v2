"""
setup_judge — realtime decision layer op basis van historical_context (PostgreSQL).

Primaire data: historical_context (31k+ records, 2022-2026, via jojo_analytics)
Recente correctie: signal_context (SQLite, laatste weken, optioneel)

Geen AI-calls.

CLI aanroep:
  python3 setup_judge.py --symbol BTCUSDT --signal BUY --rsi 32.5 --macd bullish --adx 28
  python3 setup_judge.py --symbol BTCUSDT --signal BUY --rsi 32.5 --macd bullish --adx 28 --regime bull

Python import:
  from setup_judge import judge
  result = judge("BTCUSDT", "BUY", rsi=32.5, macd="bullish", adx=28.0)
  print(result["verdict"])      # SKIP / TOESTAAN_ZWAK / TOESTAAN / STERK / ONBEKEND
  print(result["setup_score"])  # 0-100

Retourneert dict met:
  verdict       : SKIP / TOESTAAN_ZWAK / TOESTAAN / STERK / ONBEKEND
  setup_score   : 0-100 (samengestelde score)
  confidence    : laag / midden / hoog  (op basis van n)
  n             : aantal historische trades in deze setup
  avg_1h        : gemiddelde PnL 1h
  avg_4h        : gemiddelde PnL 4h
  win_pct_1h    : win percentage 1h
  regime_fit    : bull / bear / bull_voordeel / bull_nadeel / neutraal
  recent_bias   : positief / neutraal / negatief / sterk negatief
  edge_strength : geen / zwak / midden / sterk
  reden         : leesbare uitleg
  levels        : detail per niveau
"""
import sqlite3
import argparse
import json
import os

import requests

ANALYTICS_URL = os.getenv("ANALYTICS_URL", "http://jojo_analytics:8097")
DB_PATH       = os.getenv("APEX_DB", "/var/apex/apex.db")

# ── Drempels ──────────────────────────────────────────────────────────────────
SKIP_WIN_PCT        = 25.0
STERK_WIN_PCT       = 55.0
SKIP_PNL_1H         = -0.30
STERK_PNL_1H        = 0.20    # minimale economische edge voor STERK

MIN_N_VERDICT       = 10
MIN_N_COIN          = 5
MIN_N_STERK         = 20      # minimum n voor STERK verdict

CONFIDENCE_HIGH     = 50
CONFIDENCE_MEDIUM   = 20

SCORE_STERK         = 70
SCORE_TOESTAAN      = 50
SCORE_TOESTAAN_ZWAK = 30


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


def _verdict_from_score(score: int, win_pct, avg_1h, n: int) -> str:
    if n < MIN_N_VERDICT:
        return "ONBEKEND"
    # Hard SKIP: slechte win rate EN negatieve PnL tegelijk
    if (win_pct is not None and float(win_pct) < SKIP_WIN_PCT
            and avg_1h is not None and float(avg_1h) < SKIP_PNL_1H):
        return "SKIP"
    # Score-gebaseerd, met economische edge check voor STERK
    if (score >= SCORE_STERK
            and win_pct is not None and float(win_pct) >= STERK_WIN_PCT
            and avg_1h is not None and float(avg_1h) >= STERK_PNL_1H
            and n >= MIN_N_STERK):
        return "STERK"
    if score >= SCORE_TOESTAAN:
        return "TOESTAAN"
    if score >= SCORE_TOESTAAN_ZWAK:
        return "TOESTAAN_ZWAK"
    return "SKIP"


def _compute_score(win_pct, avg_1h, n: int, regime_boost: int = 0, recency_adj: int = 0) -> int:
    """Berekent setup_score 0-100.
    Componenten: win rate (0-40) + PnL (0-30) + n (0-15) + regime (0-15) + recency (-15 tot +5)
    """
    if win_pct is None or avg_1h is None:
        return 0
    score = 0
    w, p = float(win_pct), float(avg_1h)

    # Win rate (0-40)
    if w >= 55:   score += 40
    elif w >= 45: score += 30
    elif w >= 35: score += 20
    elif w >= 25: score += 10

    # PnL avg_1h (0-30)
    if p >= 0.50:    score += 30
    elif p >= 0.20:  score += 25
    elif p >= 0.05:  score += 18
    elif p >= 0.00:  score += 12
    elif p >= -0.10: score += 6
    elif p >= -0.30: score += 2

    # N (0-15)
    if n >= 100:   score += 15
    elif n >= 50:  score += 12
    elif n >= 20:  score += 8
    elif n >= 10:  score += 4

    # Regime boost (0-15)
    score += max(0, min(15, int(regime_boost)))

    # Recency aanpassing (-15 tot +5)
    score += max(-15, min(5, int(recency_adj)))

    return max(0, min(100, score))


def _edge_strength(win_pct, avg_1h, n: int) -> str:
    if win_pct is None or avg_1h is None or n < MIN_N_VERDICT:
        return "geen"
    w, p = float(win_pct), float(avg_1h)
    if w >= 55 and p >= 0.30 and n >= 30:
        return "sterk"
    if w >= 45 and p >= 0.10 and n >= 15:
        return "midden"
    if w >= 35 and p >= 0.0:
        return "zwak"
    return "negatief"


def _recent_bias(recency) -> str:
    if not recency or recency.get("avg_1h") is None:
        return "geen data"
    avg = float(recency["avg_1h"])
    win = float(recency.get("win_pct_1h") or 50)
    if avg >= 0.10 and win >= 45:
        return "positief"
    if avg <= -0.40 or win <= 30:
        return "sterk negatief"
    if avg <= -0.15:
        return "negatief"
    return "neutraal"


def _recency_adj(recency) -> int:
    if not recency or recency.get("avg_1h") is None:
        return 0
    avg = float(recency["avg_1h"])
    if avg >= 0.10:  return 5
    if avg >= 0.0:   return 0
    if avg >= -0.20: return -5
    if avg >= -0.40: return -10
    return -15


def _hctx_aggregate(where_clause: str) -> dict:
    """Haalt n/avg_1h/avg_4h/win1h + regime-split op uit historical_context.
    Geen ROUND() in SQL — adapt_query() in jojo_analytics mangelt ROUND+NULLIF.
    Ronden gebeurt in _parse_row().
    """
    rows = _query(f"""
        SELECT
            COUNT(*) as n,
            AVG(pnl_1h_pct) as avg_1h,
            AVG(pnl_4h_pct) as avg_4h,
            100.0 * SUM(CASE WHEN pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0) as win1h,
            SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END) as n_bull,
            AVG(CASE WHEN btc_regime = 'bull' THEN pnl_1h_pct END) as avg_1h_bull,
            100.0 * SUM(CASE WHEN btc_regime = 'bull' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bull' THEN 1 ELSE 0 END), 0) as win1h_bull,
            SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END) as n_bear,
            AVG(CASE WHEN btc_regime = 'bear' THEN pnl_1h_pct END) as avg_1h_bear,
            100.0 * SUM(CASE WHEN btc_regime = 'bear' AND pnl_1h_pct > 0 THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN btc_regime = 'bear' THEN 1 ELSE 0 END), 0) as win1h_bear
        FROM historical_context
        WHERE pnl_1h_pct IS NOT NULL
          AND symbol != 'USDCUSDT'
          AND {where_clause}
    """)
    return rows[0] if rows else None


def _parse_row(row) -> dict:
    """Converteert query-rij (dict van jojo_analytics) naar intern dict."""
    if not row or row.get("n") is None:
        return None
    n = int(row["n"])
    if n == 0:
        return None

    def _f(key):
        return round(float(row[key]), 3) if row.get(key) is not None else None

    def _f1(key):
        return round(float(row[key]), 1) if row.get(key) is not None else None

    return {
        "n":           n,
        "avg_1h":      _f("avg_1h"),
        "avg_4h":      _f("avg_4h"),
        "win_pct_1h":  _f1("win1h"),
        # Regime split
        "n_bull":      int(row["n_bull"])  if row.get("n_bull")  else 0,
        "avg_1h_bull": _f("avg_1h_bull"),
        "win1h_bull":  _f1("win1h_bull"),
        "n_bear":      int(row["n_bear"])  if row.get("n_bear")  else 0,
        "avg_1h_bear": _f("avg_1h_bear"),
        "win1h_bear":  _f1("win1h_bear"),
    }


def _regime_info(parsed: dict, current_regime: str) -> tuple:
    """Berekent regime_boost (0-15), regime_fit label en regime_stats dict."""
    if not parsed or not current_regime or current_regime not in ("bull", "bear"):
        return 0, "neutraal", None

    base_win   = parsed.get("win_pct_1h")
    n_regime   = parsed.get(f"n_{current_regime}", 0) or 0
    win_regime = parsed.get(f"win1h_{current_regime}")
    avg_regime = parsed.get(f"avg_1h_{current_regime}")

    if base_win is None or win_regime is None or n_regime < 5:
        return 0, current_regime, None

    delta_win = float(win_regime) - float(base_win)
    boost     = max(0, min(15, int(delta_win / 2)))

    if delta_win > 5:
        regime_fit = f"{current_regime}_voordeel"
    elif delta_win < -5:
        regime_fit = f"{current_regime}_nadeel"
    else:
        regime_fit = current_regime

    return boost, regime_fit, {
        "n":          n_regime,
        "win_pct_1h": win_regime,
        "avg_1h":     avg_regime,
        "delta_win":  round(delta_win, 1),
    }


def _get_current_btc_regime() -> str:
    """Haalt huidig BTC regime op via jojo_analytics (ema_bull van laatste 1h candle)."""
    rows = _query(
        "SELECT ema_bull FROM indicators_data "
        "WHERE symbol = 'BTCUSDT' AND interval = '1h' "
        "ORDER BY ts DESC LIMIT 1"
    )
    if not rows:
        return None
    ema_bull = rows[0].get("ema_bull")
    if ema_bull is None:
        return None
    return "bull" if ema_bull else "bear"


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
          macd: str = None, adx: float = None,
          btc_regime: str = None) -> dict:
    """
    Geeft verdict + setup_score terug voor de gegeven setup.
    Primair: historical_context (PostgreSQL, 31k+ records, 2022-2026)
    Supplemental: signal_context (SQLite, recente weken, optioneel)

    btc_regime: 'bull'/'bear'. Als None, wordt automatisch opgehaald van jojo_analytics.
    """
    rsi_zone  = _rsi_zone(rsi)
    sym       = symbol.upper()
    sig       = signal.upper()
    macd_norm = macd.lower() if macd else None
    adx_trend = (adx >= 25) if adx is not None else None

    # Haal huidig BTC regime op als niet meegegeven
    if btc_regime is None:
        btc_regime = _get_current_btc_regime()

    results = {}

    # ── Niveau 1: Generieke setup (signal + rsi_zone + macd + adx) ───────────
    if rsi_zone and macd_norm and adx_trend is not None:
        macd_clause = "(macd_hist > 0)" if macd_norm == "bullish" else "(macd_hist <= 0)"
        adx_clause  = "(adx > 25)"      if adx_trend              else "(adx <= 25)"
        row = _hctx_aggregate(
            f"signal = '{sig}' AND rsi_zone = '{rsi_zone}' "
            f"AND {macd_clause} AND {adx_clause}"
        )
        parsed = _parse_row(row)
        if parsed and parsed["n"] >= MIN_N_VERDICT:
            regime_boost, regime_fit, regime_stats = _regime_info(parsed, btc_regime)
            parsed.update({
                "confidence":   _confidence(parsed["n"]),
                "bron":         "historical_context",
                "regime_fit":   regime_fit,
                "regime_stats": regime_stats,
                "regime_boost": regime_boost,
            })
            results["generiek"] = parsed

    # ── Niveau 2: Coin-specifiek (symbol + signal + rsi_zone) ─────────────────
    if rsi_zone:
        row = _hctx_aggregate(
            f"symbol = '{sym}' AND signal = '{sig}' AND rsi_zone = '{rsi_zone}'"
        )
        parsed = _parse_row(row)
        if parsed and parsed["n"] >= MIN_N_COIN:
            regime_boost, regime_fit, regime_stats = _regime_info(parsed, btc_regime)
            parsed.update({
                "confidence":   _confidence(parsed["n"]),
                "bron":         "historical_context",
                "regime_fit":   regime_fit,
                "regime_stats": regime_stats,
                "regime_boost": regime_boost,
            })
            results["coin_rsi"] = parsed

    # ── Niveau 3: Coin-algemeen (symbol + signal) ─────────────────────────────
    row = _hctx_aggregate(f"symbol = '{sym}' AND signal = '{sig}'")
    parsed = _parse_row(row)
    if parsed and parsed["n"] >= MIN_N_COIN:
        regime_boost, regime_fit, regime_stats = _regime_info(parsed, btc_regime)
        parsed.update({
            "confidence":    _confidence(parsed["n"]),
            "bron":          "historical_context",
            "regime_fit":    regime_fit,
            "regime_stats":  regime_stats,
            "regime_boost":  regime_boost,
        })
        results["coin_algemeen"] = parsed

    # ── Recente correctielaag (signal_context, optioneel) ─────────────────────
    recency = _signal_ctx_recency(sym, sig)
    if recency:
        results["recency"] = recency

    # ── Score en verdict per niveau ───────────────────────────────────────────
    rec_adj = _recency_adj(recency)
    for key in ("generiek", "coin_rsi", "coin_algemeen"):
        if key not in results:
            continue
        d = results[key]
        score = _compute_score(
            d["win_pct_1h"], d["avg_1h"], d["n"],
            regime_boost=d.get("regime_boost", 0),
            recency_adj=rec_adj,
        )
        d["setup_score"]  = score
        d["verdict"]      = _verdict_from_score(score, d["win_pct_1h"], d["avg_1h"], d["n"])
        d["edge_strength"] = _edge_strength(d["win_pct_1h"], d["avg_1h"], d["n"])

    # ── Eindvonnis ────────────────────────────────────────────────────────────
    primary_key   = next((k for k in ("generiek", "coin_rsi", "coin_algemeen") if k in results), None)
    final_verdict = results[primary_key]["verdict"] if primary_key else "ONBEKEND"
    final_data    = results[primary_key] if primary_key else {}

    verdicts = {k: v["verdict"] for k, v in results.items()
                if k != "recency" and v.get("verdict") not in ("ONBEKEND", None)}
    conflict = len(set(verdicts.values())) > 1

    rec_bias    = _recent_bias(recency)
    regime_fit  = final_data.get("regime_fit", "neutraal")
    setup_score = final_data.get("setup_score", 0)
    edge_str    = final_data.get("edge_strength", "geen")

    reden_parts = []
    if "generiek" in results:
        g = results["generiek"]
        adx_label = "trend" if adx_trend else "range"
        reden_parts.append(
            f"Setup [{sig}+{rsi_zone}+MACD:{macd_norm}+ADX:{adx_label}]: "
            f"n={g['n']}, avg_1h={g['avg_1h']}%, win%={g['win_pct_1h']} "
            f"score={g['setup_score']} → {g['verdict']}"
        )
    if "coin_rsi" in results:
        c = results["coin_rsi"]
        reden_parts.append(
            f"{sym} [{sig}+{rsi_zone}]: "
            f"n={c['n']}, avg_1h={c['avg_1h']}%, win%={c['win_pct_1h']} "
            f"score={c['setup_score']} → {c['verdict']}"
        )
    if "coin_algemeen" in results:
        ca = results["coin_algemeen"]
        reden_parts.append(
            f"{sym} algemeen [{sig}]: "
            f"n={ca['n']}, avg_1h={ca['avg_1h']}%, win%={ca['win_pct_1h']} "
            f"score={ca['setup_score']} → {ca['verdict']}"
        )
    if recency:
        reden_parts.append(
            f"Recente data ({recency['n']} trades): "
            f"avg_1h={recency['avg_1h']}%, win%={recency['win_pct_1h']} [{rec_bias}]"
        )
    if btc_regime:
        reden_parts.append(f"BTC regime: {btc_regime} | Regime fit: {regime_fit}")
    if not reden_parts:
        reden_parts.append("Onvoldoende historische data voor dit symbool/setup.")
    if conflict:
        reden_parts.append("⚠️  Niveaus conflicteren — meest specifieke wint.")

    return {
        "symbol":        sym,
        "signal":        sig,
        "rsi":           rsi,
        "rsi_zone":      rsi_zone,
        "macd":          macd_norm,
        "adx":           adx,
        "adx_strong":    adx_trend,
        "btc_regime":    btc_regime,
        # Primaire uitkomst
        "verdict":       final_verdict,
        "setup_score":   setup_score,
        "confidence":    final_data.get("confidence", "laag"),
        "n":             final_data.get("n", 0),
        "avg_1h":        final_data.get("avg_1h"),
        "avg_4h":        final_data.get("avg_4h"),
        "win_pct_1h":    final_data.get("win_pct_1h"),
        # Uitgebreide intelligence
        "regime_fit":    regime_fit,
        "recent_bias":   rec_bias,
        "edge_strength": edge_str,
        # Meta
        "conflict":      conflict,
        "levels":        results,
        "reden":         " | ".join(reden_parts),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup judge — SKIP/TOESTAAN_ZWAK/TOESTAAN/STERK")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--signal", required=True)
    parser.add_argument("--rsi",    type=float, default=None)
    parser.add_argument("--macd",   default=None, choices=["bullish", "bearish"])
    parser.add_argument("--adx",    type=float, default=None)
    parser.add_argument("--regime", default=None, choices=["bull", "bear"],
                        help="BTC regime (auto-detect als niet opgegeven)")
    parser.add_argument("--json",   action="store_true", help="Output als JSON")
    args = parser.parse_args()

    result = judge(args.symbol, args.signal, args.rsi, args.macd, args.adx,
                   btc_regime=args.regime)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        label = {
            "SKIP":          "❌ SKIP",
            "TOESTAAN_ZWAK": "⚠️  TOESTAAN_ZWAK",
            "TOESTAAN":      "✅ TOESTAAN",
            "STERK":         "🚀 STERK",
            "ONBEKEND":      "❓ ONBEKEND",
        }
        print(f"\n{'='*55}")
        print(f"  {args.symbol} | {args.signal}")
        print(f"  RSI: {args.rsi} ({result['rsi_zone']})  MACD: {args.macd}  ADX: {args.adx}")
        print(f"  BTC regime: {result['btc_regime'] or 'onbekend'}")
        print(f"{'='*55}")
        print(f"  Verdict      : {label.get(result['verdict'], result['verdict'])}")
        print(f"  Setup Score  : {result['setup_score']}/100")
        print(f"  Confidence   : {result['confidence']}  (n={result['n']})")
        print(f"  Edge         : {result['edge_strength']}")
        print(f"  Regime fit   : {result['regime_fit']}")
        print(f"  Recente bias : {result['recent_bias']}")
        if result["avg_1h"] is not None:
            print(f"  Avg 1h PnL   : {result['avg_1h']}%")
        if result["avg_4h"] is not None:
            print(f"  Avg 4h PnL   : {result['avg_4h']}%")
        if result["win_pct_1h"] is not None:
            print(f"  Win% 1h      : {result['win_pct_1h']}%")
        print(f"\n  Onderbouwing:")
        for r in result["reden"].split(" | "):
            print(f"    {r}")
        print()
