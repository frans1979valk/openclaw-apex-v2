"""
signal_analyzer — lokale PnL analyse op signal_context + signal_performance.

Geen AI-calls. Pure SQL op apex.db.

Aanroep:
  python3 signal_analyzer.py              # volledig rapport
  python3 signal_analyzer.py --coin BTC   # enkel coin-rapport
  python3 signal_analyzer.py --skip-only  # alleen skip-tabel

Secties:
  0.  Integriteit
  1.  PnL per signaaltype       (1h / 4h apart)
  2.  PnL per RSI bucket        (1h / 4h apart)
  3.  PnL per MACD richting     (1h / 4h apart)
  4.  PnL per ADX zone          (1h / 4h apart)
  5.  PnL per coin              (gesorteerd op 1h)
  6.  Signaal × RSI             (1h)
  7.  Signaal × MACD            (1h)
  8.  Signaal × ADX             (1h)
  9.  Per-coin breakdown        (top en zwakste coins)
 10.  Combinatie-matrix         (1h, top 15)
 11.  SKIP-SCORE TABEL          (signaal × RSI × MACD)
"""
import sqlite3
import os
import sys

DB_PATH = os.getenv("APEX_DB", "/var/apex/apex.db")
MIN_N      = 3   # min. trades voor een bucket in rapport
MIN_N_SKIP = 5   # min. trades voor skip-oordeel (voorzichtiger)

# Stablecoins / ruis-symbols uitsluiten uit evaluaties
EXCLUDE_EVAL = {"USDCUSDT", "USDTUSDT", "BUSDUSDT"}

# ── Skip-engine drempels ──────────────────────────────────────────────────────
SKIP_WIN_PCT   = 25.0   # win%_1h onder → SKIP-punt
ALLOW_WIN_PCT  = 40.0   # win%_1h boven → ALLOW-punt
SKIP_PNL_1H    = -0.30  # avg_1h onder  → SKIP-punt
ALLOW_PNL_1H   =  0.00  # avg_1h boven  → ALLOW-punt


def q(con, sql):
    return con.execute(sql).fetchall()


def fmt(rows, headers, skip_col=None):
    """Tabelprinten. skip_col = index van kolom met oordeel (kleurt rijen)."""
    if not rows:
        print("  (geen data)")
        return
    col_w = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
             for i, h in enumerate(headers)]
    line = "  " + "  ".join(f"{{:<{w}}}" for w in col_w)
    print(line.format(*headers))
    print("  " + "  ".join("-" * w for w in col_w))
    for row in rows:
        print(line.format(*[str(v) if v is not None else "-" for v in row]))


def skip_label(win_pct, avg_1h, n, min_n=None):
    min_n = min_n or MIN_N_SKIP
    if n < min_n:
        return "? (n klein)"
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
        return "❌ SKIP"
    if allow_v >= 2:
        return "✅ TOESTAAN"
    return "⚠️  TWIJFEL"


BASE = """
    FROM signal_context sc
    JOIN signal_performance sp ON sp.id = sc.signal_perf_id
    WHERE sp.pnl_1h_pct IS NOT NULL
"""

RSI_CASE = """
    CASE WHEN sc.rsi_1h < 25 THEN '1_<25'
         WHEN sc.rsi_1h < 35 THEN '2_25-35'
         WHEN sc.rsi_1h < 50 THEN '3_35-50'
         WHEN sc.rsi_1h < 65 THEN '4_50-65'
         WHEN sc.rsi_1h < 75 THEN '5_65-75'
         ELSE '6_>75' END
"""

ADX_CASE = """
    CASE WHEN sc.adx IS NULL THEN '0_?'
         WHEN sc.adx < 20   THEN '1_ranging'
         WHEN sc.adx < 25   THEN '2_opbouw'
         WHEN sc.adx < 40   THEN '3_trending'
         ELSE '4_sterk' END
"""

RSI_ZONE = """
    CASE WHEN sc.rsi_1h < 35 THEN 'oversold'
         WHEN sc.rsi_1h < 50 THEN 'mid-low'
         WHEN sc.rsi_1h < 65 THEN 'mid-high'
         ELSE 'overbought' END
"""

PNL_COLS = """
    COUNT(*) as n,
    ROUND(AVG(sp.pnl_15m_pct), 3) as avg_15m,
    ROUND(AVG(sp.pnl_1h_pct),  3) as avg_1h,
    ROUND(AVG(sp.pnl_4h_pct),  3) as avg_4h,
    ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct > 0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h,
    ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct > 0 THEN 1 ELSE 0 END)/COUNT(*),1) as win4h
"""

HDR_FULL = ["n","avg_15m%","avg_1h%","avg_4h%","win%_1h","win%_4h"]


def section(title):
    print(f"\n{'─'*70}")
    print(f"  {title}")
    print(f"{'─'*70}")


def main():
    coin_filter = None
    skip_only   = False
    args = sys.argv[1:]
    if "--coin" in args:
        idx = args.index("--coin")
        coin_filter = args[idx+1].upper()
        if not coin_filter.endswith("USDT"):
            coin_filter += "USDT"
    if "--skip-only" in args:
        skip_only = True

    con = sqlite3.connect(DB_PATH)

    # ── 0. INTEGRITEIT ────────────────────────────────────────────────────────
    total_sp = con.execute("SELECT COUNT(*) FROM signal_performance").fetchone()[0]
    covered  = con.execute("SELECT COUNT(*) FROM signal_context").fetchone()[0]
    no_data  = con.execute("SELECT COUNT(*) FROM signal_context WHERE advies='NO_DATA'").fetchone()[0]
    dupes    = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT signal_perf_id FROM signal_context
            GROUP BY signal_perf_id HAVING COUNT(*) > 1)
    """).fetchone()[0]
    scope = f"AND sc.symbol='{coin_filter}'" if coin_filter else ""
    joinable = con.execute(f"SELECT COUNT(*) {BASE} {scope}").fetchone()[0]

    print("=" * 70)
    title = f"SIGNAL ANALYZER — apex.db"
    if coin_filter:
        title += f"  [{coin_filter}]"
    print(title)
    print("=" * 70)

    if not skip_only:
        print(f"\n[0] INTEGRITEIT")
        print(f"  signal_performance        : {total_sp}")
        print(f"  signal_context            : {covered} ({round(covered/total_sp*100) if total_sp else 0}% coverage)")
        print(f"  NO_DATA placeholders      : {no_data}")
        print(f"  Duplicaten                : {dupes}")
        print(f"  Analyseerbaar (ctx+pnl)   : {joinable}")

    if joinable < MIN_N:
        print(f"\n  ⚠️  Te weinig data (min. {MIN_N}).")
        con.close()
        return

    if skip_only:
        _section_skip(con, scope)
        print("=" * 70)
        con.close()
        return

    # ── 1. PER SIGNAALTYPE — 1h en 4h apart ─────────────────────────────────
    section("[1] PnL PER SIGNAALTYPE")
    print("  — 1h horizon —")
    rows = q(con, f"""
        SELECT sc.signal, {PNL_COLS} {BASE} {scope}
        GROUP BY sc.signal HAVING COUNT(*)>={MIN_N} ORDER BY avg_1h DESC
    """)
    fmt(rows, ["signal"]+HDR_FULL)

    print("\n  — 4h horizon (gesorteerd op avg_4h) —")
    rows = q(con, f"""
        SELECT sc.signal, COUNT(*) as n,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win4h
        {BASE} {scope} AND sp.pnl_4h_pct IS NOT NULL
        GROUP BY sc.signal HAVING COUNT(*)>={MIN_N} ORDER BY avg_4h DESC
    """)
    fmt(rows, ["signal","n","avg_4h%","win%_4h"])

    # ── 2. PER RSI BUCKET — 1h en 4h apart ──────────────────────────────────
    section("[2] PnL PER RSI BUCKET")
    print("  — 1h horizon —")
    rows = q(con, f"""
        SELECT {RSI_CASE} as rsi, {PNL_COLS}
        {BASE} {scope} AND sc.rsi_1h IS NOT NULL
        GROUP BY rsi HAVING COUNT(*)>={MIN_N} ORDER BY rsi
    """)
    fmt(rows, ["rsi_bucket"]+HDR_FULL)

    print("\n  — 4h horizon —")
    rows = q(con, f"""
        SELECT {RSI_CASE} as rsi, COUNT(*) as n,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win4h
        {BASE} {scope} AND sc.rsi_1h IS NOT NULL AND sp.pnl_4h_pct IS NOT NULL
        GROUP BY rsi HAVING COUNT(*)>={MIN_N} ORDER BY rsi
    """)
    fmt(rows, ["rsi_bucket","n","avg_4h%","win%_4h"])

    # ── 3. PER MACD — 1h en 4h apart ─────────────────────────────────────────
    section("[3] PnL PER MACD RICHTING")
    print("  — 1h horizon —")
    rows = q(con, f"""
        SELECT COALESCE(sc.macd_signal,'?') as macd, {PNL_COLS}
        {BASE} {scope}
        GROUP BY sc.macd_signal HAVING COUNT(*)>={MIN_N} ORDER BY avg_1h DESC
    """)
    fmt(rows, ["macd"]+HDR_FULL)

    print("\n  — 4h horizon —")
    rows = q(con, f"""
        SELECT COALESCE(sc.macd_signal,'?') as macd, COUNT(*) as n,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win4h
        {BASE} {scope} AND sp.pnl_4h_pct IS NOT NULL
        GROUP BY sc.macd_signal HAVING COUNT(*)>={MIN_N} ORDER BY avg_4h DESC
    """)
    fmt(rows, ["macd","n","avg_4h%","win%_4h"])

    # ── 4. PER ADX — 1h en 4h apart ─────────────────────────────────────────
    section("[4] PnL PER ADX ZONE")
    print("  — 1h horizon —")
    rows = q(con, f"""
        SELECT {ADX_CASE} as adx, {PNL_COLS}
        {BASE} {scope}
        GROUP BY adx HAVING COUNT(*)>={MIN_N} ORDER BY adx
    """)
    fmt(rows, ["adx_zone"]+HDR_FULL)

    print("\n  — 4h horizon —")
    rows = q(con, f"""
        SELECT {ADX_CASE} as adx, COUNT(*) as n,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win4h
        {BASE} {scope} AND sp.pnl_4h_pct IS NOT NULL
        GROUP BY adx HAVING COUNT(*)>={MIN_N} ORDER BY avg_4h DESC
    """)
    fmt(rows, ["adx_zone","n","avg_4h%","win%_4h"])

    if not coin_filter:
        # ── 5. PER COIN ───────────────────────────────────────────────────────
        section("[5] PnL PER COIN (gesorteerd op avg_1h)")
        rows = q(con, f"""
            SELECT sc.symbol, {PNL_COLS} {BASE}
            GROUP BY sc.symbol HAVING COUNT(*)>={MIN_N} ORDER BY avg_1h DESC
        """)
        fmt(rows, ["coin"]+HDR_FULL)

        section("[5b] COIN RANKING — beste / slechtste (min n={MIN_N_SKIP})")
        rows_all = q(con, f"""
            SELECT sc.symbol, COUNT(*) as n,
                ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
                ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
            {BASE}
            GROUP BY sc.symbol HAVING COUNT(*)>={MIN_N_SKIP}
            ORDER BY avg_1h DESC
        """)
        enriched = [(sym, n, avg_1h, win1h, skip_label(win1h, avg_1h, n))
                    for sym, n, avg_1h, win1h in rows_all]
        fmt(enriched, ["coin","n","avg_1h%","win%_1h","oordeel"])

    # ── 6-8. SIGNAAL × DIMENSIES ─────────────────────────────────────────────
    section("[6] SIGNAAL × RSI BUCKET (1h)")
    rows = q(con, f"""
        SELECT sc.signal, {RSI_CASE} as rsi,
            COUNT(*) as n,
            ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
        {BASE} {scope} AND sc.rsi_1h IS NOT NULL
        GROUP BY sc.signal, rsi HAVING COUNT(*)>={MIN_N}
        ORDER BY sc.signal, avg_1h DESC
    """)
    fmt(rows, ["signal","rsi","n","avg_1h%","avg_4h%","win%_1h"])

    section("[7] SIGNAAL × MACD RICHTING (1h / 4h)")
    rows = q(con, f"""
        SELECT sc.signal, COALESCE(sc.macd_signal,'?') as macd,
            COUNT(*) as n,
            ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win4h
        {BASE} {scope}
        GROUP BY sc.signal, sc.macd_signal HAVING COUNT(*)>={MIN_N}
        ORDER BY sc.signal, avg_1h DESC
    """)
    fmt(rows, ["signal","macd","n","avg_1h%","avg_4h%","win%_1h","win%_4h"])

    section("[8] SIGNAAL × ADX ZONE (1h / 4h)")
    rows = q(con, f"""
        SELECT sc.signal, {ADX_CASE} as adx,
            COUNT(*) as n,
            ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win4h
        {BASE} {scope}
        GROUP BY sc.signal, adx HAVING COUNT(*)>={MIN_N}
        ORDER BY sc.signal, avg_1h DESC
    """)
    fmt(rows, ["signal","adx_zone","n","avg_1h%","avg_4h%","win%_1h","win%_4h"])

    # ── 9. PER-COIN BREAKDOWN ─────────────────────────────────────────────────
    if coin_filter:
        section(f"[9] DETAIL BREAKDOWN — {coin_filter}")
        print("  Signaal × RSI:")
        rows = q(con, f"""
            SELECT sc.signal, {RSI_CASE} as rsi,
                COUNT(*) as n,
                ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
                ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
                ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
            {BASE} AND sc.symbol='{coin_filter}' AND sc.rsi_1h IS NOT NULL
            GROUP BY sc.signal, rsi HAVING COUNT(*)>={MIN_N}
            ORDER BY avg_1h DESC
        """)
        fmt(rows, ["signal","rsi","n","avg_1h%","avg_4h%","win%_1h"])

        print("\n  Signaal × MACD:")
        rows = q(con, f"""
            SELECT sc.signal, COALESCE(sc.macd_signal,'?') as macd,
                COUNT(*) as n,
                ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
                ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
                ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
            {BASE} AND sc.symbol='{coin_filter}'
            GROUP BY sc.signal, sc.macd_signal HAVING COUNT(*)>={MIN_N}
            ORDER BY avg_1h DESC
        """)
        fmt(rows, ["signal","macd","n","avg_1h%","avg_4h%","win%_1h"])

    # ── 10. COMBINATIE-MATRIX ────────────────────────────────────────────────
    section("[10] COMBINATIE-MATRIX — RSI × MACD × ADX (1h, top 15)")
    rows = q(con, f"""
        SELECT {RSI_ZONE} as rsi_zone,
            COALESCE(sc.macd_signal,'?') as macd,
            CASE WHEN sc.adx_strong=1 THEN 'trending' ELSE 'ranging' END as adx,
            COUNT(*) as n,
            ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
        {BASE} {scope}
        AND sc.rsi_1h IS NOT NULL AND sc.macd_signal IS NOT NULL AND sc.adx IS NOT NULL
        GROUP BY rsi_zone, macd, adx HAVING COUNT(*)>={MIN_N}
        ORDER BY avg_1h DESC LIMIT 15
    """)
    fmt(rows, ["rsi_zone","macd","adx","n","avg_1h%","avg_4h%","win%_1h"])

    # ── 11. SKIP-SCORE ───────────────────────────────────────────────────────
    _section_skip(con, scope)

    # ── 12. VERDICT EVALUATIE ────────────────────────────────────────────────
    _section_verdict_eval(con, scope)

    print("\n" + "=" * 70)
    con.close()


def _section_skip(con, scope=""):
    section(f"[11] SKIP-ENGINE TABEL  (min n={MIN_N_SKIP})")
    print(f"  SKIP    : win%_1h < {SKIP_WIN_PCT}  EN  avg_1h < {SKIP_PNL_1H}")
    print(f"  TOESTAAN: win%_1h >= {ALLOW_WIN_PCT} EN  avg_1h >= {ALLOW_PNL_1H}")
    print(f"  Anders  : TWIJFEL\n")

    rows = q(con, f"""
        SELECT sc.signal,
            {RSI_ZONE} as rsi_zone,
            COALESCE(sc.macd_signal,'?') as macd,
            {ADX_CASE} as adx_zone,
            COUNT(*) as n,
            ROUND(AVG(sp.pnl_1h_pct),3) as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct),3) as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
        {BASE} {scope}
        AND sc.rsi_1h IS NOT NULL AND sc.macd_signal IS NOT NULL AND sc.adx IS NOT NULL
        GROUP BY sc.signal, rsi_zone, macd, adx_zone
        HAVING COUNT(*)>={MIN_N_SKIP}
        ORDER BY avg_1h DESC
    """)

    if not rows:
        print("  (nog niet genoeg data — verhoog coverage of verlaag MIN_N_SKIP)")
        return

    enriched = []
    for row in rows:
        signal, rsi_zone, macd, adx_zone, n, avg_1h, avg_4h, win1h = row
        label = skip_label(win1h, avg_1h, n)
        enriched.append((signal, rsi_zone, macd, adx_zone, n, avg_1h, avg_4h, win1h, label))

    # Gegroepeerd tonen: SKIP eerst, dan TWIJFEL, dan TOESTAAN
    for verdict in ["❌ SKIP", "⚠️  TWIJFEL", "✅ TOESTAAN"]:
        subset = [r for r in enriched if r[-1] == verdict]
        if not subset:
            continue
        print(f"  {verdict}")
        fmt(subset, ["signal","rsi_zone","macd","adx_zone","n","avg_1h%","avg_4h%","win%_1h","oordeel"])
        print()


def _section_verdict_eval(con, scope=""):
    # Bouw exclude clause
    if EXCLUDE_EVAL:
        excl = ",".join(f"'{s}'" for s in EXCLUDE_EVAL)
        excl_clause = f"AND vl.symbol NOT IN ({excl})"
    else:
        excl_clause = ""
    """
    Evalueer hoe SKIP / TWIJFEL / TOESTAAN presteren op daadwerkelijke uitkomsten.
    Koppelt verdict_log aan signal_performance via signal_perf_id.
    """
    # Check of verdict_log bestaat en gevuld is
    try:
        total_vl = con.execute("SELECT COUNT(*) FROM verdict_log").fetchone()[0]
    except Exception:
        return
    if total_vl == 0:
        return

    section(f"[12] VERDICT EVALUATIE  (n={total_vl} verdicts gelogd)")
    print("  Toets: presteren SKIP/TWIJFEL/TOESTAAN zoals verwacht op echte uitkomsten?\n")

    coin_clause = ""
    if scope:
        # scope is iets als "AND sc.symbol='BTCUSDT'" — omzetten voor verdict_log
        coin_clause = scope.replace("sc.symbol", "vl.symbol")

    # ── 12a. Per verdict — 1h en 4h ─────────────────────────────────────────
    print(f"  (USDCUSDT en stablecoins uitgesloten)\n")
    print("  — Per verdict (1h en 4h) —")
    rows = q(con, f"""
        SELECT
            vl.verdict,
            COUNT(*) as n,
            ROUND(AVG(sp.pnl_1h_pct), 3)  as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct), 3)  as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct > 0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_4h_pct > 0 THEN 1 ELSE 0 END)/
                NULLIF(SUM(CASE WHEN sp.pnl_4h_pct IS NOT NULL THEN 1 ELSE 0 END),0),1) as win4h
        FROM verdict_log vl
        JOIN signal_performance sp ON sp.id = vl.signal_perf_id
        WHERE sp.pnl_1h_pct IS NOT NULL {coin_clause} {excl_clause}
        GROUP BY vl.verdict
        ORDER BY avg_1h DESC
    """)
    if rows:
        fmt(rows, ["verdict","n","avg_1h%","avg_4h%","win%_1h","win%_4h"])
    else:
        print("  (verdict_log heeft nog geen gekoppelde PnL uitkomsten)")

    # ── 12b. Per verdict per coin ────────────────────────────────────────────
    if not scope:
        print("\n  — Per verdict per coin (min n=3) —")
        rows = q(con, f"""
            SELECT
                vl.verdict,
                vl.symbol,
                COUNT(*) as n,
                ROUND(AVG(sp.pnl_1h_pct), 3) as avg_1h,
                ROUND(AVG(sp.pnl_4h_pct), 3) as avg_4h,
                ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h
            FROM verdict_log vl
            JOIN signal_performance sp ON sp.id = vl.signal_perf_id
            WHERE sp.pnl_1h_pct IS NOT NULL {excl_clause}
            GROUP BY vl.verdict, vl.symbol
            HAVING COUNT(*) >= 3
            ORDER BY vl.verdict, avg_1h DESC
        """)
        if rows:
            fmt(rows, ["verdict","coin","n","avg_1h%","avg_4h%","win%_1h"])
        else:
            print("  (nog niet genoeg data per coin per verdict)")

    # ── 12c. Vergelijking: zou skippen winst geven? ──────────────────────────
    print("\n  — SKIP-waarde: wat zou je missen vs. vermijden? —")
    rows = q(con, f"""
        SELECT
            vl.verdict,
            ROUND(AVG(sp.pnl_1h_pct),3)  as avg_1h,
            ROUND(AVG(sp.pnl_4h_pct),3)  as avg_4h,
            ROUND(100.0*SUM(CASE WHEN sp.pnl_1h_pct>0 THEN 1 ELSE 0 END)/COUNT(*),1) as win1h,
            COUNT(*) as n
        FROM verdict_log vl
        JOIN signal_performance sp ON sp.id = vl.signal_perf_id
        WHERE sp.pnl_1h_pct IS NOT NULL {coin_clause} {excl_clause}
        GROUP BY vl.verdict
        ORDER BY CASE vl.verdict
            WHEN 'SKIP'      THEN 1
            WHEN 'TWIJFEL'   THEN 2
            WHEN 'TOESTAAN'  THEN 3
            ELSE 4 END
    """)
    if rows:
        # Bereken wat het zou opleveren als je alleen TOESTAAN handelt
        toestaan = next((r for r in rows if r[0] == "TOESTAAN"), None)
        skip     = next((r for r in rows if r[0] == "SKIP"),     None)
        twijfel  = next((r for r in rows if r[0] == "TWIJFEL"),  None)
        alle     = con.execute(f"""
            SELECT ROUND(AVG(sp.pnl_1h_pct),3), COUNT(*)
            FROM verdict_log vl
            JOIN signal_performance sp ON sp.id = vl.signal_perf_id
            WHERE sp.pnl_1h_pct IS NOT NULL {coin_clause} {excl_clause}
        """).fetchone()

        print(f"  Alle trades samen : avg_1h={alle[0]}%  n={alle[1]}")
        if toestaan:
            print(f"  Alleen TOESTAAN  : avg_1h={toestaan[1]}%  win%={toestaan[3]}  n={toestaan[4]}")
        if twijfel:
            print(f"  Alleen TWIJFEL   : avg_1h={twijfel[1]}%  win%={twijfel[3]}  n={twijfel[4]}")
        if skip:
            print(f"  Alleen SKIP      : avg_1h={skip[1]}%  win%={skip[3]}  n={skip[4]}")

        if toestaan and alle[0] is not None and toestaan[1] is not None:
            diff = round(float(toestaan[1]) - float(alle[0]), 3)
            prefix = "+" if diff >= 0 else ""
            print(f"\n  → Alleen TOESTAAN vs. alles: {prefix}{diff}% per trade op 1h")

    # ── 12d. Verdict match-rate ──────────────────────────────────────────────
    print("\n  — Verdict match-rate (klopt de richting?) —")
    rows = q(con, f"""
        SELECT
            vl.verdict,
            COUNT(*) as n,
            ROUND(100.0*SUM(CASE
                WHEN vl.verdict='SKIP'     AND sp.pnl_1h_pct <= 0 THEN 1
                WHEN vl.verdict='TOESTAAN' AND sp.pnl_1h_pct >  0 THEN 1
                WHEN vl.verdict='TWIJFEL'  THEN 1  -- twijfel telt altijd als 'ok'
                ELSE 0 END)/COUNT(*),1) as correct_pct
        FROM verdict_log vl
        JOIN signal_performance sp ON sp.id = vl.signal_perf_id
        WHERE sp.pnl_1h_pct IS NOT NULL {coin_clause} {excl_clause}
          AND vl.verdict IN ('SKIP','TWIJFEL','TOESTAAN')
        GROUP BY vl.verdict
        ORDER BY correct_pct DESC
    """)
    if rows:
        fmt(rows, ["verdict","n","correct%"])
        print("  (correct% = SKIP→verlies, TOESTAAN→winst, TWIJFEL→altijd meegeteld)")


if __name__ == "__main__":
    main()
