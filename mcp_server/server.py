"""
OpenClaw MCP Server
Geeft Claude (web/desktop) directe toegang tot het OpenClaw trading platform.
Transport: Streamable HTTP op poort 8100
Beveiliging: Bearer token via Authorization header
"""
import os, requests
from fastmcp import FastMCP

CONTROL_API_URL      = os.getenv("CONTROL_API_URL", "http://control_api:8080")
INDICATOR_ENGINE_URL = os.getenv("INDICATOR_ENGINE_URL", "http://indicator_engine:8099")
CONTROL_API_TOKEN    = os.getenv("CONTROL_API_TOKEN", "changeme-strong-token")
MCP_AUTH_TOKEN       = os.getenv("MCP_AUTH_TOKEN", "")

mcp = FastMCP("OpenClaw Trading Platform")

def _headers():
    return {"X-API-KEY": CONTROL_API_TOKEN}

def _ctrl(path: str, method="GET", json=None, params=None):
    url = f"{CONTROL_API_URL}{path}"
    r = requests.request(method, url, headers=_headers(), json=json, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def _ind(path: str, method="GET", json=None, params=None):
    url = f"{INDICATOR_ENGINE_URL}{path}"
    r = requests.request(method, url, json=json, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

# ── Tools: Account & Status ──────────────────────────────────────────────────

@mcp.tool()
def get_balance() -> dict:
    """Haal demo account balans op: P&L, win rate, aantal trades."""
    return _ctrl("/balance")

@mcp.tool()
def get_market_state() -> dict:
    """
    Haal huidige marktstate op: alle geselecteerde coins met prijs, RSI,
    MACD, signaal, timeframe bias, Kimi redenering en flash crash status.
    """
    return _ctrl("/state/latest")

@mcp.tool()
def get_signal_performance(limit: int = 50) -> list:
    """
    Haal signal performance statistieken op per coin+signaal combinatie.
    Toont win rate, gemiddeld P&L en aantal trades per patroon.
    """
    return _ctrl("/signal-performance", params={"limit": limit})

@mcp.tool()
def get_orders(limit: int = 50) -> list:
    """Haal recente orders/trades op uit de demo account."""
    return _ctrl("/orders", params={"limit": limit})

# ── Tools: Historische data (indicator_engine) ──────────────────────────────

@mcp.tool()
def get_indicator_signal(symbol: str, interval: str = "1h") -> dict:
    """
    Haal indicator signaal op voor een coin op basis van 4 jaar historische data.
    Geeft: signaal (BUY/SELL/HOLD), confidence, aantal precedenten, win rate,
    gemiddeld P&L 1h en 4h, worst case scenario, en patroon fingerprint.

    Voorbeeld: get_indicator_signal("BTCUSDT", "1h")
    """
    return _ind(f"/signal/{symbol}", params={"interval": interval})

@mcp.tool()
def get_patterns(symbol: str) -> list:
    """
    Haal alle historische patroon-combinaties op voor een coin.
    Geeft per rsi_zone + macd_direction combinatie: win rate, avg P&L,
    aantal trades en worst case. Gesorteerd op win rate.

    Voorbeeld: get_patterns("BTCUSDT")
    """
    data = _ind(f"/patterns/{symbol}")
    if isinstance(data, list):
        return sorted(data, key=lambda x: x.get("win_rate", 0), reverse=True)
    return data

@mcp.tool()
def get_data_coverage() -> list:
    """
    Haal een overzicht op van alle beschikbare historische data:
    welke coins, welke intervals, hoeveel candles en van welke periode.
    """
    return _ind("/coverage")

@mcp.tool()
def run_strategy_backtest(
    symbols: list,
    interval: str = "1h",
    btc_filter: bool = False,
    rsi_buy_threshold: float = 30.0,
    rsi_chop_max: float = 55.0,
    stoploss_pct: float = 2.0,
    takeprofit_pct: float = 4.5,
    max_positions: int = 3,
) -> dict:
    """
    Voer een strategie backtest uit op historische data (tot 4 jaar).
    Test verschillende parameters en vergelijk resultaten.

    Parameters:
    - symbols: lijst van coins bijv. ["BTCUSDT", "ETHUSDT", "DOGEUSDT"]
    - interval: "1h" of "4h"
    - btc_filter: blokkeer altcoin longs als BTC bearish is
    - rsi_buy_threshold: maximale RSI voor entry (bijv. 30)
    - rsi_chop_max: skip chop zone (geen entry als RSI tussen threshold en chop_max)
    - stoploss_pct: stoploss percentage (bijv. 2.0 = 2%)
    - takeprofit_pct: take profit percentage (bijv. 4.5 = 4.5%)
    - max_positions: maximale gelijktijdige posities

    Geeft terug: totaal trades, win rate, totaal P&L, max drawdown, profit factor per coin.
    """
    payload = {
        "symbols": symbols,
        "interval": interval,
        "btc_filter": btc_filter,
        "rsi_buy_threshold": rsi_buy_threshold,
        "rsi_chop_max": rsi_chop_max,
        "stoploss_pct": stoploss_pct,
        "takeprofit_pct": takeprofit_pct,
        "max_positions": max_positions,
    }
    return _ind("/backtest/strategy", method="POST", json=payload)

@mcp.tool()
def get_top_coins(limit: int = 20) -> list:
    """
    Haal de top coins op van Binance gesorteerd op 24h USDT volume.
    Handig voor het bepalen welke coins het meest actief zijn.
    """
    return _ind("/top-coins", params={"limit": limit})

# ── Tools: Config & Proposals ──────────────────────────────────────────────

@mcp.tool()
def get_proposals(status: str = "pending") -> list:
    """
    Haal config proposals op. Status: 'pending', 'applied', of 'all'.
    Proposals zijn configuratiewijzigingen die wachten op goedkeuring.
    """
    return _ctrl("/proposals", params={"status": status})

@mcp.tool()
def propose_config(params: dict, reason: str) -> dict:
    """
    Stel een configuratiewijziging voor aan apex_engine.
    Veranderingen worden pas actief na goedkeuring via apply_proposal.

    Voorbeeldparameters:
    - rsi_buy_threshold: 28
    - stoploss_pct: 2.5
    - takeprofit_pct: 5.0
    - max_positions: 2
    - skip_coins: ["UNIUSDT", "DOTUSDT"]

    Voorbeeld: propose_config({"rsi_buy_threshold": 25}, "Strengere RSI na backtest analyse")
    """
    payload = {"agent": "MCP/Claude", "params": params, "reason": reason}
    return _ctrl("/config/propose", method="POST", json=payload)

@mcp.tool()
def apply_proposal(proposal_id: int) -> dict:
    """
    Pas een goedgekeurde proposal toe op apex_engine.
    Gebruik get_proposals() om de beschikbare proposals te zien.
    """
    return _ctrl(f"/proposals/{proposal_id}/apply", method="POST")

# ── Tools: Trading control ─────────────────────────────────────────────────

@mcp.tool()
def trading_halt() -> dict:
    """NOODSTOP: Stop alle trading onmiddellijk. Gebruik trading_resume() om te hervatten."""
    return _ctrl("/trading/halt", method="POST")

@mcp.tool()
def trading_resume() -> dict:
    """Hervat trading na een noodstop of pauze."""
    return _ctrl("/trading/resume", method="POST")

@mcp.tool()
def trading_pause(minutes: int = 30, reason: str = "handmatige pauze via MCP") -> dict:
    """Pauzeer trading voor X minuten."""
    return _ctrl("/trading/pause", method="POST",
                 json={"minutes": minutes, "reason": reason})

@mcp.tool()
def get_trading_status() -> dict:
    """Haal huidige trading status op: actief, gepauzeerd of gestopt."""
    return _ctrl("/trading/status")

# ── Resources ─────────────────────────────────────────────────────────────

@mcp.resource("openclaw://platform/status")
def platform_status() -> str:
    """Volledig platform overzicht als resource."""
    try:
        balance = _ctrl("/balance")
        state   = _ctrl("/state/latest")
        coins   = state.get("coins", [])

        lines = [
            "# OpenClaw Platform Status",
            f"",
            f"## Account",
            f"Balans: ${balance.get('balance', 0):,.2f}",
            f"P&L: {balance.get('pnl_total_pct', 0):+.2f}%",
            f"Win rate: {balance.get('win_rate_pct', 0)}%",
            f"Trades: {balance.get('total_orders', 0)}",
            f"",
            f"## Actieve coins ({len(coins)})",
        ]
        for c in coins:
            lines.append(
                f"- {c.get('symbol','?')}: ${c.get('price',0):.4f} "
                f"({c.get('change_pct',0):+.2f}%) "
                f"{c.get('signal','?')} RSI:{c.get('rsi',0) or 0:.0f}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Fout bij ophalen status: {e}"

@mcp.resource("openclaw://backtest/aanbevolen")
def backtest_aanbevolen() -> str:
    """Aanbevolen coin configuratie op basis van backtest resultaten (2026-03-06)."""
    return """# Backtest Resultaten — Aanbevolen Configuratie

## Beste coins (top 8 — winstgevend als groep)
- DOGEUSDT: 43.3% win rate, +21.49% totaal P&L (BESTE coin)
- BNBUSDT:  47.1% win rate (hoge wr maar avg P&L negatief)
- LINKUSDT: 38.5% win rate, +7.04% totaal P&L
- ETHUSDT:  34.3% win rate, +1.23% totaal P&L
- SEIUSDT:  36.4% win rate
- AAVEUSDT: 36.4% win rate
- APTUSDT:  36.6% win rate
- LTCUSDT:  42.3% win rate

## Coins om te vermijden (historisch slecht)
- UNIUSDT:  24.1% win rate, -1.22% avg P&L (SLECHTSTE)
- DOTUSDT:  25.0% win rate, -0.70% avg P&L
- ATOMUSDT: 25.9% win rate, -0.98% avg P&L
- XRPUSDT:  26.7% win rate, -1.70% avg P&L
- AVAXUSDT: 30.6% win rate, -0.52% avg P&L
- ARBUSDT:  32.0% win rate, -0.70% avg P&L

## Aanbevolen parameters
- rsi_buy_threshold: 30
- rsi_chop_max: 55
- stoploss_pct: 2.0
- takeprofit_pct: 4.5
- max_positions: 2
- skip_coins: UNIUSDT, DOTUSDT, ATOMUSDT, XRPUSDT, AVAXUSDT, ARBUSDT, SOLUSDT, ADAUSDT

## Verwacht resultaat
Win rate: ~38-40% (huidig live: 25.3%)
P&L top 8: +3.98% (eerste winstgevende configuratie)
"""

if __name__ == "__main__":
    import uvicorn
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            if not MCP_AUTH_TOKEN:
                return await call_next(request)
            auth  = request.headers.get("Authorization", "")
            token = request.query_params.get("token", "")
            if auth == f"Bearer {MCP_AUTH_TOKEN}" or token == MCP_AUTH_TOKEN:
                return await call_next(request)
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

    async def health_endpoint(request):
        return JSONResponse({"status": "ok", "service": "openclaw-mcp"})

    port    = int(os.getenv("MCP_PORT", "8100"))
    mcp_app = mcp.http_app(transport="streamable-http", path="/mcp")

    app = Starlette(
        routes=[
            Route("/health", health_endpoint),
            Mount("/", app=mcp_app),
        ],
        middleware=[Middleware(BearerAuthMiddleware)],
        lifespan=mcp_app.router.lifespan_context,
    )
    uvicorn.run(app, host="0.0.0.0", port=port)
