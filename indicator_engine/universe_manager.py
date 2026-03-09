"""
Universe Manager — dagelijkse top-50 market cap refresh + stablecoin filter.
Vervangt de statische SAFE_COINS env-var als primaire coin-bron voor indicator_engine.
"""
import json, logging, os, threading
from datetime import datetime, timezone

import requests as req

log = logging.getLogger("universe_manager")

# ── Config ────────────────────────────────────────────────────────────────────
COINGECKO_URL  = "https://api.coingecko.com/api/v3/coins/markets"
MIN_VOLUME_USD = float(os.getenv("UNIVERSE_MIN_VOLUME_USD", "30_000_000"))  # 30M USDT/24h
MIN_MCAP_USD   = float(os.getenv("UNIVERSE_MIN_MCAP_USD",   "100_000_000")) # 100M USD

# Bekende stablecoins (CoinGecko IDs)
STABLECOIN_IDS = frozenset({
    "tether", "usd-coin", "dai", "binance-usd", "true-usd",
    "frax", "usdd", "paypal-usd", "first-digital-usd", "paxos-standard",
    "gemini-dollar", "liquity-usd", "ethena-usde", "mountain-protocol-usdm",
    "crvusd", "euro-coin", "nusd", "origin-dollar", "dola-usd",
    "fei-usd", "usdk", "eurs", "seur", "usds", "savings-usds",
    "usd-coin", "usdg", "usdm", "usyc", "buidl",
    "sky", "usdb", "first-digital-usd",
})

# Bekende stablecoins (Binance base-symbol, zonder USDT)
STABLECOIN_SYMS = frozenset({
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FRAX", "USDD", "PYUSD",
    "FDUSD", "USDP", "GUSD", "LUSD", "USDE", "CRVUSD", "EURC", "OUSD",
    "DOLA", "SUSD", "EURS", "USDK", "USDS", "USDG", "USDM", "USYC",
    "BUIDL", "USDF",
})

# USDT is de quote currency — kan niet als USDTUSDT gehandeld worden
SKIP_SYMS = frozenset({"USDT"})

# Fallback statische lijst (gebruikt als CoinGecko onbereikbaar is)
TOP50_FALLBACK = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT",  "SOLUSDT",  "XRPUSDT",  "DOGEUSDT",
    "ADAUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT",  "DOTUSDT",  "MATICUSDT",
    "LTCUSDT", "ATOMUSDT","NEARUSDT", "XLMUSDT",   "AAVEUSDT", "ALGOUSDT",
    "UNIUSDT", "ETCUSDT", "VETUSDT",  "HBARUSDT",  "INJUSDT",  "APTUSDT",
    "ARBUSDT", "OPUSDT",  "SUIUSDT",  "SEIUSDT",   "FETUSDT",  "TIAUSDT",
    "BCHUSDT", "ICPUSDT", "TAOUSDT",  "ZECUSDT",   "RENDERUSDT","ENAUSDT",
    "WLDUSDT", "PEPEUSDT","SHIBUSDT", "BONKUSDT",  "WIFUSDT",  "FLOKIUSDT",
    # stablecoins voor monitoring (active_for_trading=False)
    "USDCUSDT", "TUSDUSDT", "FDUSDUSDT",
]

# ── Module state ──────────────────────────────────────────────────────────────
_lock            = threading.Lock()
_universe: list  = []            # list of coin dicts
_last_refresh: datetime | None = None
_refresh_source: str = "none"


# ── Helpers ───────────────────────────────────────────────────────────────────
def _is_stablecoin(cg_id: str, sym: str) -> bool:
    return cg_id.lower() in STABLECOIN_IDS or sym.upper() in STABLECOIN_SYMS


def _to_binance(sym: str) -> str:
    s = sym.upper()
    return s if s.endswith("USDT") else s + "USDT"


# ── Fetch ─────────────────────────────────────────────────────────────────────
def _fetch_coingecko() -> list:
    """Haalt top-60 coins van CoinGecko (gratis, geen API-key)."""
    try:
        r = req.get(COINGECKO_URL, params={
            "vs_currency": "usd",
            "order":       "market_cap_desc",
            "per_page":    60,
            "page":        1,
            "sparkline":   "false",
        }, timeout=25)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            log.info(f"[universe] CoinGecko: {len(data)} coins opgehaald")
            return data
    except Exception as e:
        log.warning(f"[universe] CoinGecko fout: {e}")
    return []


def _build_universe(raw: list, source: str) -> list:
    """Verwerk ruwe CoinGecko data naar universe list (max 50 coins)."""
    result = []
    rank   = 0
    seen   = set()

    for c in raw:
        cg_id   = c.get("id", "")
        sym_raw = c.get("symbol", "").upper()
        name    = c.get("name", "")
        mcap    = int(c.get("market_cap") or 0)
        vol24   = int(c.get("total_volume") or 0)

        if sym_raw in SKIP_SYMS:
            continue

        bsym = _to_binance(sym_raw)
        if bsym in seen:
            continue
        seen.add(bsym)

        rank += 1
        if rank > 50:
            break

        stable = _is_stablecoin(cg_id, sym_raw)

        if stable:
            active_trade = False
            active_mon   = True
            dq           = 1.0
        else:
            ok_vol       = vol24 >= MIN_VOLUME_USD
            ok_mcap      = mcap  >= MIN_MCAP_USD
            active_trade = ok_vol and ok_mcap
            active_mon   = True
            # Data quality score 0.0 – 1.0
            dq = round(
                min(1.0, vol24 / (MIN_VOLUME_USD * 20)) * 0.5 +
                min(1.0, mcap  / (MIN_MCAP_USD  * 100)) * 0.5, 3
            )

        result.append({
            "symbol":               bsym,
            "name":                 name,
            "rank":                 rank,
            "market_cap_usd":       mcap,
            "volume_24h_usd":       vol24,
            "is_stablecoin":        stable,
            "active_for_trading":   active_trade,
            "active_for_monitoring":active_mon,
            "data_quality_score":   dq,
            "source":               source,
        })

    return result


def _fallback_universe() -> list:
    """Statische fallback universe als CoinGecko onbereikbaar is."""
    result = []
    for i, bsym in enumerate(TOP50_FALLBACK, 1):
        sym    = bsym.replace("USDT", "")
        stable = sym in STABLECOIN_SYMS
        result.append({
            "symbol":               bsym,
            "name":                 sym,
            "rank":                 i,
            "market_cap_usd":       0,
            "volume_24h_usd":       0,
            "is_stablecoin":        stable,
            "active_for_trading":   not stable,
            "active_for_monitoring":True,
            "data_quality_score":   0.5,
            "source":               "fallback",
        })
    return result


# ── Public API ────────────────────────────────────────────────────────────────
def refresh(get_conn_fn, adapt_query_fn) -> dict:
    """
    Haalt top-50 op van CoinGecko (met statische fallback), slaat op in DB.
    Retourneert summary dict.
    """
    global _universe, _last_refresh, _refresh_source

    raw    = _fetch_coingecko()
    source = "coingecko" if raw else "fallback"
    new_u  = _build_universe(raw, source) if raw else _fallback_universe()

    if not new_u:
        return {"ok": False, "error": "Lege universe na verwerking"}

    # DB upsert
    try:
        conn = get_conn_fn()
        cur  = conn.cursor()

        for c in new_u:
            cur.execute(adapt_query_fn("""
                INSERT INTO universe_coins
                    (symbol, name, rank, market_cap_usd, volume_24h_usd,
                     is_stablecoin, active_for_trading, active_for_monitoring,
                     data_quality_score, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    name=EXCLUDED.name,
                    rank=EXCLUDED.rank,
                    market_cap_usd=EXCLUDED.market_cap_usd,
                    volume_24h_usd=EXCLUDED.volume_24h_usd,
                    is_stablecoin=EXCLUDED.is_stablecoin,
                    active_for_trading=EXCLUDED.active_for_trading,
                    active_for_monitoring=EXCLUDED.active_for_monitoring,
                    data_quality_score=EXCLUDED.data_quality_score,
                    source=EXCLUDED.source,
                    updated_at=NOW()
            """), (
                c["symbol"], c["name"], c["rank"],
                c["market_cap_usd"], c["volume_24h_usd"],
                c["is_stablecoin"], c["active_for_trading"],
                c["active_for_monitoring"], c["data_quality_score"],
                c["source"],
            ))

        cur.execute(adapt_query_fn("""
            INSERT INTO universe_history (coins_json, source, rank_count)
            VALUES (?, ?, ?)
        """), (
            json.dumps([c["symbol"] for c in new_u]),
            source, len(new_u),
        ))

        conn.commit()
        conn.close()
        log.info(f"[universe] DB bijgewerkt: {len(new_u)} coins, bron={source}")

    except Exception as e:
        log.error(f"[universe] DB fout: {e}")

    ts_now = datetime.now(timezone.utc)
    with _lock:
        _universe       = new_u
        _last_refresh   = ts_now
        _refresh_source = source

    trading = sum(1 for c in new_u if c["active_for_trading"])
    stables = sum(1 for c in new_u if c["is_stablecoin"])
    excluded = sum(1 for c in new_u if not c["active_for_trading"] and not c["is_stablecoin"])

    log.info(
        f"[universe] Refresh klaar: {trading} trading, {stables} stablecoins, "
        f"{excluded} uitgesloten (liquiditeit), bron={source}"
    )
    return {
        "ok": True,
        "total": len(new_u),
        "trading_coins": trading,
        "stablecoins": stables,
        "excluded": excluded,
        "source": source,
        "ts": ts_now.isoformat(),
    }


def load_from_db(get_conn_fn, adapt_query_fn):
    """Laad universe vanuit DB bij startup (vermijdt CoinGecko call bij herstart)."""
    global _universe, _last_refresh, _refresh_source
    try:
        conn = get_conn_fn()
        cur  = conn.cursor()
        cur.execute(adapt_query_fn("""
            SELECT symbol, name, rank, market_cap_usd, volume_24h_usd,
                   is_stablecoin, active_for_trading, active_for_monitoring,
                   data_quality_score, source, updated_at
            FROM universe_coins ORDER BY rank ASC
        """))
        rows = cur.fetchall()
        conn.close()

        if rows:
            u = []
            for r in rows:
                u.append({
                    "symbol":               r[0],
                    "name":                 r[1],
                    "rank":                 r[2],
                    "market_cap_usd":       r[3] or 0,
                    "volume_24h_usd":       r[4] or 0,
                    "is_stablecoin":        bool(r[5]),
                    "active_for_trading":   bool(r[6]),
                    "active_for_monitoring":bool(r[7]),
                    "data_quality_score":   float(r[8]) if r[8] else 0.0,
                    "source":               r[9] or "db",
                    "updated_at":           (
                        r[10].isoformat()
                        if hasattr(r[10], "isoformat") else str(r[10])
                    ),
                })
            with _lock:
                _universe       = u
                _last_refresh   = datetime.now(timezone.utc)
                _refresh_source = "db"
            log.info(f"[universe] {len(u)} coins geladen vanuit DB")

    except Exception as e:
        log.warning(f"[universe] DB load mislukt (tabel bestaat nog niet?): {e}")


def get_universe() -> list:
    """Huidig universe als list van dicts (thread-safe kopie)."""
    with _lock:
        return list(_universe)


def get_trading_coins() -> list[str]:
    """Symbols actief voor trading (geen stablecoins, voldoende liquiditeit)."""
    with _lock:
        if not _universe:
            return []
        return [c["symbol"] for c in _universe if c["active_for_trading"]]


def get_stablecoin_monitoring() -> list[str]:
    """Stablecoin symbols actief voor depeg monitoring."""
    with _lock:
        if not _universe:
            return []
        return [c["symbol"] for c in _universe if c["is_stablecoin"] and c["active_for_monitoring"]]


def get_meta() -> dict:
    """Meta-info over laatste refresh."""
    with _lock:
        return {
            "ts":            _last_refresh.isoformat() if _last_refresh else None,
            "source":        _refresh_source,
            "total":         len(_universe),
            "trading_coins": sum(1 for c in _universe if c["active_for_trading"]),
            "stablecoins":   sum(1 for c in _universe if c["is_stablecoin"]),
        }
