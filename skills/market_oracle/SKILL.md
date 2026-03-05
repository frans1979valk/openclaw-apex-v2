---
name: market_oracle
description: "Market Oracle — macro-economische en geopolitieke analyse via RSS feeds, Yahoo Finance en nieuwsbronnen. Levert structured JSON context voor trading beslissingen."
metadata:
  openclaw:
    emoji: "🔮"
    requires:
      bins:
        - curl
---

# Market Oracle Skill

Je hebt toegang tot de Market Oracle sandbox service. Deze draait in een geïsoleerde container **zonder exchange keys of AI keys**. De oracle leest alleen publieke RSS feeds, Yahoo Finance en nieuwsbronnen.

## Gebruik

Roep de sandbox endpoint aan via bash:

### Event analyse

```bash
curl -s -X POST http://market_oracle_sandbox:8095/run_event \
  -H "Content-Type: application/json" \
  -d '{"event": "US Fed raises rates by 50bps", "focus": "btc,eth,gold"}'
```

### URL analyse

```bash
curl -s -X POST http://market_oracle_sandbox:8095/run_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.reuters.com/markets/"}'
```

### Volledige scan (geen input, scant alle RSS feeds)

```bash
curl -s http://market_oracle_sandbox:8095/scan
```

## Output formaat

Alle endpoints geven structured JSON:

```json
{
  "ok": true,
  "analysis": {
    "short_term": { "outlook": "bearish", "confidence": 0.7 },
    "medium_term": { "outlook": "neutral", "confidence": 0.5 },
    "long_term": { "outlook": "bullish", "confidence": 0.6 }
  },
  "contrarian_risk": 0.3,
  "key_factors": ["Fed rate hike", "USD strength", "Risk-off sentiment"],
  "suggested_actions": ["PAUSE", "TIGHTEN_STOPLOSS"],
  "timestamp": "2026-03-05T20:00:00Z"
}
```

## Regels

- Output is **alleen adviserend** — nooit direct trades uitvoeren
- `suggested_actions` mag alleen resulteren in **voorstellen** (PAUSE, NO_BUY, TIGHTEN_STOPLOSS)
- Elke actie op basis van oracle output vereist Telegram bevestiging (behalve flash-crash PAUSE)
- De oracle heeft **geen** API keys, exchange keys, of LLM keys
- De oracle leest alleen van publieke bronnen via internet
