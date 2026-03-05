---
name: macro_context_oracle
description: "Macro Context Oracle — roept de Market Oracle sandbox aan, stuurt samenvattingen naar Telegram, en update de control_api context store."
metadata:
  openclaw:
    emoji: "🌐"
    requires:
      bins:
        - curl
---

# Macro Context Oracle

Je gebruikt deze skill om macro-economische context op te halen via de Market Oracle sandbox service. De sandbox draait geïsoleerd (geen AI/exchange keys) en analyseert publieke RSS feeds + Yahoo Finance.

## Stap 1: Oracle aanroepen

### Event analyse
```bash
curl -s -X POST http://market_oracle_sandbox:8095/run_event \
  -H "Content-Type: application/json" \
  -d '{"event": "US CPI data hoger dan verwacht", "focus": "btc,eth,gold,sp500"}'
```

### Volledige marktscan
```bash
curl -s http://market_oracle_sandbox:8095/scan
```

### URL analyse
```bash
curl -s -X POST http://market_oracle_sandbox:8095/run_url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://reuters.com/article/..."}'
```

## Stap 2: Context updaten in control_api

Stuur het oracle resultaat naar control_api als read-only context:
```bash
curl -s -X POST http://control_api:8080/context/macro \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -d '<oracle JSON output>'
```

## Stap 3: Actie op basis van resultaat

Bekijk `suggested_actions` in de oracle output:

| Oracle actie | Jouw reactie |
|-------------|--------------|
| `PAUSE` | Dien een PAUSE-voorstel in via gatekeeper skill |
| `NO_BUY` | Dien een parameter-voorstel in (conservative settings) |
| `TIGHTEN_STOPLOSS` | Stel stoploss_pct verlagen voor (bijv. van 4% naar 2.5%) |
| `RESUME` | Als trading gepauzeerd is, stel hervatten voor |
| (leeg) | Geen actie nodig — rapporteer alleen |

## Regels

- **Oracle output is adviserend** — nooit direct uitvoeren
- Elke actie moet via de **gatekeeper skill** als voorstel worden ingediend
- Alleen PAUSE mag automatisch (flash-crash policy) — alle andere acties vereisen Telegram bevestiging
- Geef altijd een **samenvatting** in Telegram: outlook, key factors, voorgestelde actie
- Macro context mag **nooit** leiden tot ALLOW_LIVE=true of directe exchange calls
