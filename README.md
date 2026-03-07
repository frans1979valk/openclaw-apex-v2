# OpenClaw Apex Trading Platform v2

Een volledig autonome AI crypto trading bot met 16 Docker containers, 40 coins, 4 jaar historische data en een Sniper Bot. Draait op BloFin in **demo (paper trading)** mode.

> Volledige documentatie: [docs/PLATFORM_INFO.md](docs/PLATFORM_INFO.md)

---

## Architectuur (16 containers)

| Service | Beschrijving | Poort |
|---|---|---|
| `apex_engine` | Trading engine — AI filters, signalen, BloFin demo orders | — |
| `control_api` | REST API + config + proposals + auth | 8080 |
| `indicator_engine` | 40 coins x 4jr historische data + TA + Sniper Bot | 8099 |
| `postgres` | PostgreSQL 16 database (17 tabellen) | 5432 |
| `openclaw_gateway` | Jojo1 AI operator (Claude Sonnet 4.6 + Telegram) | 18789 |
| `tg_discuss_bot` | Kimi AI chat bot (@franscryptoinlog_bot) | — |
| `tg_coordinator_bot` | Elke 30min marktrapport naar Telegram | — |
| `command_center` | Beveiligde webinterface (Telegram OTP auth) | 4000 |
| `jojo_analytics` | TA indicators + DB queries service | 8097 |
| `kimi_pattern_agent` | Nachtelijke patroonanalyse (03:00 dagelijks) | 8098 |
| `market_oracle_sandbox` | Publieke RSS + Yahoo Finance (geen API keys) | 8095 |
| `dashboard` | Nginx web dashboard | 3000 |
| `openclaw` / `openclaw_runtime` | OpenClaw framework runtime | — |
| `mcp_server` | MCP server voor Claude Web (staat uit) | 8100 |
| `cloudflare_tunnel` | HTTPS voor MCP (staat uit) | — |

---

## OpenClaw — Het Masterframework

**OpenClaw is de ruggengraat van het hele platform.** Het is het agent-runtime framework waarop Jojo1 draait — niet slechts een "gateway", maar het brein dat alle platform-componenten coördineert.

### Wat is OpenClaw?

OpenClaw is een TypeScript-gebaseerd operator OS voor autonome AI agents. Het combineert:
- **Claude Sonnet 4.6** als taalmodel (Jojo's intelligentie)
- **Telegram interface** als primair communicatiekanaal
- **Tool systeem** — Python scripts die Jojo kan aanroepen (indicator_engine, control_api, sniper, etc.)
- **Skill systeem** — complexe workflows als herbruikbare "skills"
- **Multi-agent coördinatie** — Jojo kan sub-agents aansturen (Research Agent, Risk Agent)
- **Persistent memory** — Jojo onthoudt context over sessies heen
- **Collab systeem** — gestructureerde communicatie tussen Jojo en Dev via inbox bestanden

### Jojo1 als AI Operator

Jojo1 (draait in `openclaw_gateway`) is **geen simpele chatbot**. Het is een autonome operator die:

1. **Marktdata opvraagt** via tool_intelligence.py → indicator_engine
2. **Config wijzigt** via proposals → control_api → apex_engine
3. **Snipers instelt** via tool_sniper.py → indicator_engine
4. **Trading beheert** via trading_halt.json, skip_coins, max_positions
5. **Analyses maakt** via Research Agent + Risk Agent sub-workflows
6. **Rapporteert** naar Frans via Telegram

### OpenClaw Architectuur

```
Frans (Telegram)
     │
     ▼
openclaw_gateway (OpenClaw runtime — TypeScript)
     │
     ├── Claude Sonnet 4.6 (Jojo's taalmodel)
     │
     ├── Tools:
     │    ├── tool_intelligence.py → indicator_engine:8099
     │    ├── tool_sniper.py       → indicator_engine:8099
     │    ├── tool_market.py       → market_oracle:8095
     │    └── tool_analytics.py   → jojo_analytics:8097
     │
     ├── Control:
     │    └── proposals → control_api:8080 → apex_engine config
     │
     └── Collab:
          └── /workspace/collab/inbox/ ↔ Dev (Claude Code)
```

### Waarom OpenClaw de "master" is

Zonder OpenClaw is het platform een verzameling losse microservices. OpenClaw maakt het tot een **autonoom systeem**:
- Alle beslissingen gaan via Jojo1 (OpenClaw)
- Jojo coördineert wanneer welke service wordt aangesproken
- Jojo interpreteert marktdata en zet het om in acties
- Jojo communiceert met Frans en Dev als enige centrale operator

---

## Features

### Trading Filters (apex_engine)
1. **Trading halt** — hardcoded stop via `trading_halt.json`
2. **Skip coins** — configureerbaar via proposals
3. **BTC EMA200 filter (4h)** — geen longs als BTC bearish op 4h
4. **BTC EMA21/55 filter (1h)** — geen altcoin longs in bear market
5. **Pre-crash score** — geblokkeerd bij score >= 60/100
6. **RSI filter** — RSI < drempel (default 30)
7. **RSI chop zone** — geen BUY in RSI 30-55 neutrale zone
8. **Signal blacklist** — automatisch op basis van historische PnL
9. **Pattern engine** — 1h + 4h bevestiging vereist
10. **Max posities** — default 4 gelijktijdige posities

### Indicator Engine (40 coins, 4 jaar data)
- RSI, MACD, EMA21/55/200, Bollinger Bands, ADX, StochRSI, ATR
- Historische patroon matching + win rates
- Backtest op 4 jaar data
- **Reverse backtest**: vindt pre-crash fingerprints
- **Sniper Bot**: wacht op perfecte entry condities

### Sniper Bot
```
/sniper dip BTC [rsi=28]           -- wacht op dip entry
/sniper short ETH [rsi=68]         -- wacht op short entry
/sniper niveau BTC target=80000    -- prijs alert
/sniper breakout SOL               -- breakout conditie
/sniper list / cancel <id>
/sniper reverse BTC [threshold=-5] -- crash analyse
```

### MCP Server (Claude Web toegang)
Wanneer Jojo geen credits heeft, kan Claude Web alsnog alle data raadplegen:
```bash
docker compose up -d mcp_server cloudflare_tunnel
docker logs ...-cloudflare_tunnel-1 | grep trycloudflare  # HTTPS URL
```
Token: zie `secrets/mcp_server.env`

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/frans1979valk/openclaw-apex-v2.git
cd openclaw-apex-v2

# 2. Secrets aanmaken (zie secrets/*.env.example)
# Vul alle *.env bestanden in met jouw API keys

# 3. Starten
docker compose up -d

# 4. Controleer
docker compose ps
curl http://localhost:8080/balance -H "X-API-KEY: <token>"
curl http://localhost:8099/health
```

---

## Config aanpassen (proposals)

```bash
curl -X POST http://localhost:8080/config/propose \
  -H "X-API-KEY: <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "Dev",
    "params": {
      "rsi_buy_threshold": 28,
      "rsi_chop_max": 55,
      "max_positions": 3,
      "skip_coins": ["DOTUSDT", "UNIUSDT"]
    },
    "reason": "Verbeterde filters"
  }'

curl -X POST http://localhost:8080/proposals/1/apply \
  -H "X-API-KEY: <token>"
```

---

## Telegram bots

| Bot | Handle | Functie |
|-----|--------|---------|
| Jojo1 | @franstest1_bot | AI operator (Claude) |
| Kimi Chat | @franscryptoinlog_bot | Marktanalyse + Sniper |

**Kimi Chat commando's:**
```
/status        -- marktoverzicht
/balance       -- demo balans
/patroon BTC   -- historische patroonanalyse
/signal ETH 4h -- indicator signaal
/backtest BTC  -- strategie backtest
/sniper dip BTC -- sniper instellen
/stop / /start -- trading beheer
```

---

## 40 Gevolgde Coins

**Origineel (17):** BTC, ETH, SOL, AAVE, AVAX, LINK, DOT, UNI, LTC, DOGE, XRP, BNB, ADA, ATOM, ARB, APT, SEI

**Nieuw toegevoegd (23):** SUI, TRX, NEAR, BCH, ICP, HBAR, PEPE, WIF, WLD, ENA, TAO, ZEC, OP, XLM, SHIB, FET, BONK, FLOKI, RENDER, INJ, TIA, ALGO, VET

---

## Secrets

Alle secrets in `secrets/*.env` — **nooit in git**.

| Bestand | Inhoud |
|---------|--------|
| `apex.env` | BloFin API + Kimi key (apex_engine agents) |
| `postgres.env` | DATABASE_URL + POSTGRES_PASSWORD |
| `openclaw_gateway.env` | ANTHROPIC_API_KEY voor Jojo1 |
| `telegram_discuss.env` | Kimi bot token + KIMI_API_KEY |
| `mcp_server.env` | MCP_AUTH_TOKEN |

---

## Veiligheidsregels

- `TRADING_MODE=demo` en `ALLOW_LIVE=false` zijn hardcoded
- PARAM_BOUNDS gehandhaafd door control_api
- Max 3 config wijzigingen per dag
- Max dagverlies 5% automatische pauze
- Jojo1 kan nooit live trading inschakelen

---

## Documentatie

- [docs/PLATFORM_INFO.md](docs/PLATFORM_INFO.md) — volledige technische documentatie
- [docs/SYSTEM_FULL.md](docs/SYSTEM_FULL.md) — uitgebreide systeemdocumentatie
- [docs/INDICATOR_ENGINE.md](docs/INDICATOR_ENGINE.md) — indicator engine details

---

*Stack: Python 3.12, FastAPI, PostgreSQL 16, TA-Lib, Docker Compose, Claude Sonnet 4.6, Kimi moonshot-v1-32k, FastMCP 3.1*
