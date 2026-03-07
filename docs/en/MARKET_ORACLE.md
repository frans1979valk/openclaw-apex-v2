# Market Oracle — Guide

## What is this?

The Market Oracle is an isolated macro-economic analysis engine that processes public RSS feeds and Yahoo Finance data into structured JSON output. OpenClaw uses this output as context for trading decisions.

## Architecture

```
OpenClaw Gateway
    ↓ macro_context_oracle skill
    ↓ curl (HTTP)
market_oracle_sandbox (:8095)
    ├── RSS feeds (Reuters, NYT, CoinDesk)
    ├── Yahoo Finance (BTC, ETH, gold, oil, S&P500, DXY, VIX)
    └── URL scraping (BeautifulSoup)
    ↓ JSON output
    ↓ curl (HTTP)
control_api (:8080) → context store (read-only)
```

**The sandbox container NEVER has:**
- Exchange API keys
- AI/LLM API keys
- Access to `secrets/` files
- Direct trading permissions

## Endpoints

### POST /run_event

Analyze a specific market event.

```bash
curl -s -X POST http://127.0.0.1:8095/run_event \
  -H "Content-Type: application/json" \
  -d '{"event": "US Fed raises rates by 50bps", "focus": "btc,eth,gold"}'
```

**Response:**
```json
{
  "ok": true,
  "analysis": {
    "short_term": { "outlook": "bearish", "confidence": 0.7 },
    "medium_term": { "outlook": "neutral", "confidence": 0.5 },
    "long_term": { "outlook": "bullish", "confidence": 0.6 }
  },
  "contrarian_risk": 0.3,
  "key_factors": ["US Fed raises rates by 50bps", "Markets tumble on rate fears", ...],
  "suggested_actions": ["PAUSE", "NO_BUY"],
  "prices": {
    "btc": { "price": 62450.00, "change_5d_pct": -3.2 },
    "gold": { "price": 2180.50, "change_5d_pct": 1.1 }
  },
  "timestamp": "2026-03-05T20:00:00Z"
}
```

### POST /run_url

Analyze a specific news article.

```bash
curl -s -X POST http://127.0.0.1:8095/run_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.reuters.com/markets/global-markets-overview"}'
```

### GET /scan

Full macro scan (all RSS feeds + all tickers).

```bash
curl -s http://127.0.0.1:8095/scan
```

### GET /health

```bash
curl -s http://127.0.0.1:8095/health
```

## Testing

```bash
# Build the sandbox
docker compose build market_oracle_sandbox

# Start
docker compose up -d market_oracle_sandbox

# Health check
curl -s http://127.0.0.1:8095/health

# Test event analysis
curl -s -X POST http://127.0.0.1:8095/run_event \
  -H "Content-Type: application/json" \
  -d '{"event": "Bitcoin ETF approved by SEC", "focus": "btc,eth"}' | python3 -m json.tool

# Test full scan
curl -s http://127.0.0.1:8095/scan | python3 -m json.tool
```

## Suggested Actions → Gatekeeper proposals

The oracle output contains `suggested_actions`. These may **never** be executed directly. OpenClaw converts them into Gatekeeper proposals:

| Oracle action | Gatekeeper proposal |
|--------------|---------------------|
| `PAUSE` | `POST /proposals { type: "PAUSE" }` |
| `NO_BUY` | `POST /proposals { type: "PARAM_CHANGE", payload: {conservative} }` |
| `TIGHTEN_STOPLOSS` | `POST /proposals { type: "PARAM_CHANGE", payload: {stoploss_pct: lower value} }` |
| `RESUME` | `POST /proposals { type: "RESUME" }` |

All proposals require Telegram confirmation, except PAUSE on flash-crash (crash_score > 70).

## Security

- Container runs with resource limits: 0.5 CPU, 256MB RAM
- No access to `./secrets/` (no volume mount)
- Only on `agent_net` network (can reach `control_api`, but not `apex_engine`)
- Tools mounted read-only (`./skills/market_oracle/tools:/workspace/tools:ro`)
- No outbound domain allowlist (Python `requests` can reach all public URLs — standard internet for RSS/yfinance)

## Files

```
skills/market_oracle/
├── SKILL.md                    ← OpenClaw skill definition
└── tools/
    ├── requirements.txt        ← Python dependencies
    └── oracle.py               ← Analysis engine

skills/macro_context_oracle/
└── SKILL.md                    ← OpenClaw skill that calls the sandbox

market_oracle_sandbox/
├── Dockerfile                  ← Python 3.12 slim + pip install
└── main.py                     ← FastAPI wrapper
```
