# OpenClaw Trading Platform — BloFin Demo v2

Een volledig autonome crypto trading bot met AI-gestuurde coin selectie, multi-exchange analyse, zelfoptimalisatie en Telegram bediening. Draait op BloFin in demo (paper trading) modus.

---

## Architectuur

```
┌─────────────────────────────────────────────────────────────┐
│                     OpenClaw Platform                        │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐ │
│  │ apex_engine │───▶│ control_api │◀───│    openclaw     │ │
│  │  (trading)  │    │  (hersenen) │    │  (leer-agent)   │ │
│  └─────────────┘    └──────┬──────┘    └─────────────────┘ │
│                            │                                 │
│  ┌─────────────┐    ┌──────▼──────┐    ┌─────────────────┐ │
│  │  dashboard  │◀───│  SQLite DB  │    │  tg_bots (2x)   │ │
│  │  (port 3000)│    │  /var/apex  │    │  Telegram UI    │ │
│  └─────────────┘    └─────────────┘    └─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Containers

| Service | Beschrijving | Port |
|---|---|---|
| `apex_engine` | Trading engine — signalen, orders, BloFin executor | — |
| `control_api` | REST API + state manager + auth | 8080 |
| `openclaw` | Autonome leer-agent (Kimi + ClawBot) | — |
| `dashboard` | Web controlecentrum (Nginx) | **3000** |
| `tg_discuss_bot` | Telegram discussie + commando interface | — |
| `tg_coordinator_bot` | Telegram coördinatie bot | — |

---

## Features

### Trading Engine (apex_engine)
- **Kimi AI coin selectie** — selecteert elke cyclus de 5 beste USDT pairs op basis van volume, RSI en marktdata
- **BloFin spot trading** — volledig geïntegreerd met BloFin demo API
- **Multi-timeframe signalen** — BUY, SELL, HOLD, PERFECT_DAY, BREAKOUT_BULL, MOMENTUM, DANGER
- **Pre-crash detector** — blokkeert kopen bij score > 60/100
- **Exchange Intel** — gewogen consensus van 5 exchanges (Coinbase 35%, Binance 25%, Bybit 20%, OKX 12%, Kraken 8%)
- **Flash crash detectie** — pauzeer automatisch bij plotselinge prijsdaling
- **Nieuws monitor** — CryptoPanic integratie
- **Coin whitelist** — 40 veilige coins (SAFE_COINS) + BloFin-beschikbare coins met Telegram goedkeuring

### Leer-agent (openclaw)
- **Learning loop** — elke 30 min: analyseert signal performance → Kimi optimaliseert RSI/stoploss parameters
- **Backtest loop** — elke 60 min: historische backtest voor gevolgde coins
- **Beslissingsloop** — elke 15 min: ClawBot (Claude) autonome marktanalyse
- **Veiligheidsgrenzen** — parameters nooit buiten hardcoded PARAM_BOUNDS
- **Max 3 parameterwijzigingen per dag**

### Dashboard (port 3000)
- Live prijs feeds (SSE)
- Balans en P&L tracking
- Signal performance tabel
- Multi-exchange prijsvergelijking (6 exchanges)
- Pre-crash meter
- Historische data grafieken
- OTP login (via Telegram)

### Telegram Interface
- `/status` — marktoverzicht
- `/coins` — Kimi's coin selectie met redenering
- `/balance` — demo balans en P&L
- `/backtest [SYMBOL]` — historische backtest
- `/stop` — noodstop
- `/start` — hervatten
- `/pauzeer [min]` — tijdelijke pauze
- `/coingoedkeuren` — nieuwe coins goedkeuren/afwijzen
- `/clawbot [sonnet|haiku]` — Claude model instellen
- `/zoek [query]` — web search via DuckDuckGo

---

## Installatie

### Vereisten
- Docker + Docker Compose
- Python 3.12+ (alleen voor lokale ontwikkeling)
- API keys (zie hieronder)

### Stap 1: Kloon de repo
```bash
git clone https://github.com/frans1979valk/openclaw-apex-v2.git
cd openclaw-apex-v2
```

### Stap 2: Kopieer en vul de secrets in
```bash
cp secrets/apex.env.example              secrets/apex.env
cp secrets/control_api.env.example       secrets/control_api.env
cp secrets/openclaw.env.example          secrets/openclaw.env
cp secrets/telegram_coordinator.env.example  secrets/telegram_coordinator.env
cp secrets/telegram_discuss.env.example  secrets/telegram_discuss.env
```

Vul de `.env` bestanden in met jouw API keys (zie sectie API Keys hieronder).

### Stap 3: Start het platform
```bash
docker compose up -d
```

### Stap 4: Open het dashboard
```
http://jouw-server-ip:3000
```

---

## API Keys

| Key | Waar te krijgen | Env bestand |
|---|---|---|
| `BLOFIN_API_KEY/SECRET/PASSPHRASE` | [blofin.com](https://blofin.com) → API Management | `apex.env` |
| `KIMI_API_KEY` (Moonshot) | [platform.moonshot.cn](https://platform.moonshot.cn) | `apex.env`, `openclaw.env`, `telegram_discuss.env` |
| `ANTHROPIC_API_KEY` (Claude) | [console.anthropic.com](https://console.anthropic.com) | `openclaw.env` |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) op Telegram | `telegram_*.env` |
| `TELEGRAM_ALLOWED_USERS` | Jouw Telegram user ID (via [@userinfobot](https://t.me/userinfobot)) | `telegram_discuss.env` |
| `CRYPTOPANIC_TOKEN` | [cryptopanic.com/developers/api](https://cryptopanic.com/developers/api/) (gratis) | `apex.env` |

---

## Configuratie

### apex.env — Trading parameters
```env
TRADING_MODE=demo          # demo of live
ALLOW_LIVE=false           # zet op true voor echte trades
PRE_CRASH_BUY_BLOCK=60     # kopen geblokkeerd boven dit getal (0-100)
EXCHANGE_INTEL_ENABLED=true
```

### control_api.env — Veiligheidsgrenzen
```env
MIN_PROFIT_FACTOR=1.15     # minimum profit factor voor auto-apply
MAX_DRAWDOWN_PCT=6         # maximale drawdown
MAX_APPLIES_PER_DAY=3      # max parameterwijzigingen per dag
```

### Parameter bounds (hardcoded in openclaw/bot.py)
```python
PARAM_BOUNDS = {
    "rsi_buy_threshold":  (20, 40),
    "rsi_sell_threshold": (60, 80),
    "stoploss_pct":       (1.5, 6.0),
    "takeprofit_pct":     (3.0, 12.0),
    "position_size_base": (1, 5),
}
```

---

## Veiligheid

- `secrets/*.env` bestanden zijn uitgesloten van git (via `.gitignore`)
- Dashboard gebruikt OTP authenticatie via Telegram
- Control API gebruikt bearer token authenticatie
- Trading is standaard in **demo modus** (`ALLOW_LIVE=false`)
- Noodstop via `/stop` in Telegram of dashboard
- Coin selectie vereist Telegram goedkeuring voor nieuwe/onbekende coins

---

## OpenClaw Framework Integratie

Dit platform integreert het [openclaw/openclaw](https://github.com/openclaw/openclaw) framework als multi-agent runtime.

### Architectuur

```
┌─────────────────────────────────────────────────────┐
│                openclaw_runtime                      │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────┐  │
│  │ research_    │ │ strategy_    │ │ risk_       │  │
│  │ agent        │ │ agent        │ │ agent       │  │
│  │ (read-only)  │ │ (propose)    │ │ (pause)     │  │
│  └──────┬───────┘ └──────┬───────┘ └──────┬──────┘  │
│         └────────────────┼────────────────┘          │
│                    Kimi LLM (Moonshot)                │
└─────────────────────────┬───────────────────────────┘
                          │ HTTP tools
                          ▼
              ┌───────────────────────┐
              │     control_api        │
              │  :8080 (FastAPI)       │
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │     apex_engine        │
              │  (BloFin demo trades)  │
              └───────────────────────┘
```

### Agents

| Agent | Interval | Bevoegdheden |
|-------|----------|--------------|
| `research_agent` | 1 uur | Lezen: status, backtest, nieuws |
| `strategy_agent` | 2 uur | + Voorstellen: propose_params |
| `risk_agent` | 30 min | + Schrijven: pause/resume trading |

### Agent endpoints (openclaw_runtime :8090)

```
POST /agents/research   — handmatig research starten
POST /agents/strategy   — handmatig strategy starten
POST /agents/risk       — handmatig risk check starten
GET  /agents/status     — overzicht intervals + tools
GET  /health            — health check
```

### Beschikbare tools

Zie `openclaw_tools/registry.json` voor de volledige registry.

| Tool | Schrijf | Beschrijving |
|------|---------|--------------|
| `tool_status` | Nee | Markt + engine status |
| `tool_run_backtest` | Nee | Backtest uitvoeren |
| `tool_fetch_news` | Nee | Recente events |
| `tool_propose_params` | Ja | Parameter voorstel indienen |
| `tool_apply_proposal` | Ja | Voorstel toepassen (vereist /ok) |
| `tool_pause_trading` | Ja | Trading pauzeren |
| `tool_resume_trading` | Ja | Trading hervatten |

### Parameter grenzen (PARAM_BOUNDS)

| Parameter | Min | Max |
|-----------|-----|-----|
| `rsi_buy_threshold` | 20 | 40 |
| `rsi_sell_threshold` | 60 | 80 |
| `stoploss_pct` | 1.5 | 6.0 |
| `takeprofit_pct` | 3.0 | 12.0 |
| `position_size_base` | 1 | 5 |

### Verschil openclaw.bot vs openclaw/openclaw vs dit platform

| | openclaw.bot | openclaw/openclaw | Dit platform |
|-|-------------|-------------------|--------------|
| Type | Chat aggregator app | TypeScript AI framework | Python trading platform |
| Doel | Chat UI met meerdere AI's | Personal AI agent runtime | Crypto auto-trading |
| Basis | Commercieel product | Open source framework | Dit repo |

---

## Projectstructuur

```
openclaw-apex-v2/
├── apex_engine/           # Trading engine
│   └── app/
│       ├── core/
│       │   ├── indicators.py      # RSI, MACD, ATR berekeningen
│       │   ├── kimi_selector.py   # AI coin selectie
│       │   ├── pre_crash.py       # Crash detectie
│       │   ├── data_logger.py     # Historische data opslag
│       │   └── db.py              # SQLite schema
│       └── exchanges/
│           ├── binance_feed.py    # Binance + BloFin feed
│           └── bybit_feed.py      # Bybit feed
├── control_api/           # REST API (FastAPI)
│   └── app/server.py
├── openclaw/              # Leer-agent (Claude + Kimi)
│   ├── bot.py
│   └── clawbot.py
├── openclaw_runtime/      # Multi-agent orchestrator (nieuw)
│   ├── main.py            # FastAPI + agent runner
│   └── Dockerfile
├── openclaw_tools/        # Agent tools (nieuw)
│   ├── registry.json      # Tool registry
│   ├── scripts/           # tool_*.py scripts
│   └── prompts/           # *_agent.md prompts
├── openclaw_framework/    # openclaw/openclaw submodule (nieuw)
│   └── Dockerfile.runtime # Node.js 22 gateway build
├── dashboard/             # Web UI (HTML/JS/Nginx)
│   └── index.html
├── telegram/
│   ├── discuss_bot/       # Discussie + commando bot
│   └── coordinator_bot/   # Coördinatie bot
├── secrets/               # API keys (NIET in git)
│   ├── *.env              # Echte keys (gitignored)
│   └── *.env.example      # Templates (in git)
├── install.sh             # Eerste installatie
├── update.sh              # Update naar laatste versie
├── doctor.sh              # Diagnose platform health
└── docker-compose.yml
```

---

## Bijdragen

Dit is een privé project. Voel je vrij om te forken voor eigen gebruik.

---

## Licentie

Privé gebruik. Geen garanties — gebruik op eigen risico. Crypto trading brengt financiële risico's met zich mee.
