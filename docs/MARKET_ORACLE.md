# Market Oracle — Handleiding

## Wat is dit?

De Market Oracle is een geïsoleerde macro-economische analyse engine die publieke RSS feeds en Yahoo Finance data verwerkt tot structured JSON output. OpenClaw gebruikt deze output als context voor trading beslissingen.

## Architectuur

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

**De sandbox container heeft NOOIT:**
- Exchange API keys
- AI/LLM API keys
- Toegang tot `secrets/` bestanden
- Directe trading bevoegdheid

## Endpoints

### POST /run_event

Analyseer een specifiek markt-event.

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

Analyseer een specifiek nieuwsartikel.

```bash
curl -s -X POST http://127.0.0.1:8095/run_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.reuters.com/markets/global-markets-overview"}'
```

### GET /scan

Volledige macro scan (alle RSS feeds + alle tickers).

```bash
curl -s http://127.0.0.1:8095/scan
```

### GET /health

```bash
curl -s http://127.0.0.1:8095/health
```

## Testen

```bash
# Build de sandbox
docker compose build market_oracle_sandbox

# Start
docker compose up -d market_oracle_sandbox

# Health check
curl -s http://127.0.0.1:8095/health

# Test event analyse
curl -s -X POST http://127.0.0.1:8095/run_event \
  -H "Content-Type: application/json" \
  -d '{"event": "Bitcoin ETF approved by SEC", "focus": "btc,eth"}' | python3 -m json.tool

# Test volledige scan
curl -s http://127.0.0.1:8095/scan | python3 -m json.tool
```

## Suggested Actions → Gatekeeper voorstellen

De oracle output bevat `suggested_actions`. Deze mogen **nooit** direct uitgevoerd worden. OpenClaw zet ze om naar Gatekeeper proposals:

| Oracle actie | Gatekeeper proposal |
|-------------|---------------------|
| `PAUSE` | `POST /proposals { type: "PAUSE" }` |
| `NO_BUY` | `POST /proposals { type: "PARAM_CHANGE", payload: {conservative} }` |
| `TIGHTEN_STOPLOSS` | `POST /proposals { type: "PARAM_CHANGE", payload: {stoploss_pct: lagere waarde} }` |
| `RESUME` | `POST /proposals { type: "RESUME" }` |

Alle proposals vereisen Telegram bevestiging, behalve PAUSE bij flash-crash (crash_score > 70).

## Security

- Container draait met resource limits: 0.5 CPU, 256MB RAM
- Geen toegang tot `./secrets/` (geen volume mount)
- Alleen op `agent_net` netwerk (kan `control_api` bereiken, maar niet `apex_engine`)
- Tools gemount als read-only (`./skills/market_oracle/tools:/workspace/tools:ro`)
- Geen outbound domain allowlist (Python `requests` kan alle publieke URLs bereiken — standaard internet voor RSS/yfinance)

## Bestanden

```
skills/market_oracle/
├── SKILL.md                    ← OpenClaw skill definitie
└── tools/
    ├── requirements.txt        ← Python dependencies
    └── oracle.py               ← Analyse engine

skills/macro_context_oracle/
└── SKILL.md                    ← OpenClaw skill die sandbox aanroept

market_oracle_sandbox/
├── Dockerfile                  ← Python 3.12 slim + pip install
└── main.py                     ← FastAPI wrapper
```
