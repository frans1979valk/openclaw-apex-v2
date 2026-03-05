# OpenClaw + Apex — BloFin Demo Trading Platform (v2)

Demo/paper trading platform met AI-gestuurde signalen, historische backtest engine, Telegram login, en live dashboard.

---

## Architectuur

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose                           │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ apex_engine  │    │ control_api  │    │   dashboard      │  │
│  │  (Python)    │    │  (FastAPI)   │    │  (nginx + HTML)  │  │
│  │              │    │              │    │                  │  │
│  │ • Trading    │    │ • REST API   │    │ • Live dashboard │  │
│  │ • Signalen   │    │ • Backtest   │    │ • Telegram login │  │
│  │ • AI agents  │◄──►│ • Auth OTP   │◄──►│ • Historische    │  │
│  │ • Flash crash│    │ • Balance    │    │   backtest UI    │  │
│  │              │    │              │    │                  │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────────────┘  │
│         │                  │                                    │
│         └──────────────────┘                                    │
│              apex_data volume (/var/apex/apex.db)               │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  openclaw    │    │ tg_coord_bot │    │  tg_discuss_bot  │  │
│  │  (agents)    │    │  (logging)   │    │  (commando's)    │  │
│  └──────────────┘    └──────────────┘    └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Services

### 1. apex_engine — Trading Engine
**Poort:** intern (geen publieke poort)
**Bestand:** `apex_engine/app/main.py`

Draait continu in een loop van 10 seconden:

| Stap | Interval | Beschrijving |
|------|----------|--------------|
| Kimi scan | 5 min | Haalt top-30 movers op van Binance via `select_best_coins()` |
| Indicatoren | elke loop | RSI, MACD, EMA21/55/200, ADX, BB, StochRSI, ATR, wick-filter |
| Flash crash | elke loop | Detecteert snelle prijsdalingen, plaatst direct buy |
| Signal logging | 15 min | Logt BUY/PERFECT_DAY signalen voor P&L evaluatie |
| Signal evaluatie | elke loop | Kijkt terug: wat deed de prijs +15min/+1u/+4u na het signaal? |
| AI agent workflow | 30 min | Research → Strategy → Risk → Verify (via Kimi K2.5) |
| State write | elke loop | Schrijft JSON naar `/var/apex/bot_state.json` |

#### Strategieën (5 stuks)
| Naam | Conditie | Signal |
|------|----------|--------|
| RSI-MACD | RSI<32 + MACD hist>0 + wick<0.6 | BUY |
| BB-Squeeze | BB width<2.5% + price>upper BB | BUY |
| Golden Cross | EMA21>EMA55>EMA200 | BUY |
| StochRSI | StochRSI K<20, K>D, RSI<45 | BUY |
| ADX | ADX>25, +DI>-DI | BUY |
| PERFECT_DAY ⭐ | RSI-MACD + (BB-Squeeze) + (GoldenCross) + ADX | PERFECT_DAY |
| BREAKOUT_BULL | price>upperBB + RSI>50 + vol>1.5×avg | BREAKOUT_BULL |
| MOMENTUM | GoldenCross + 50<RSI<65 + MACD>0 + ADX | MOMENTUM |

**XRP-specifieke filters (uit 161125xrp):**
- Wick-to-ATR max 0.6 (geen slechte wick entries)
- Round-number proximity tracking (0.50, 0.75, 1.00, etc.)

---

### 2. control_api — REST API
**Poort:** `0.0.0.0:8080`
**Bestand:** `control_api/app/server.py`

#### Endpoints

| Method | Pad | Auth | Beschrijving |
|--------|-----|------|--------------|
| POST | `/auth/request` | open | Vraag OTP-code aan (stuurt via Telegram) |
| POST | `/auth/verify` | open | Verifieer code, krijg 24u sessie token terug |
| GET | `/health` | open | Health check |
| GET | `/state/latest` | ✓ | Laatste bot state (coins, signalen, agent) |
| GET | `/balance` | ✓ | Demo account balans + order statistieken |
| GET | `/signal-performance` | ✓ | Historische signaal P&L evaluaties |
| GET | `/backtest/{symbol}` | ✓ | Snelle backtest (500 candles) |
| GET | `/backtest/historical/{symbol}` | ✓ | Historische backtest (tot MAX) |
| GET | `/backtest/historical/{symbol}/signals` | ✓ | Individuele signalen uit backtest |
| GET | `/proposals` | ✓ | Agent proposals lijst |
| POST | `/config/propose` | ✓ | Nieuwe proposal indienen |
| POST | `/proposals/{id}/apply` | ✓ | Proposal toepassen |

**Query parameters historische backtest:**
- `months=3/6/12/24` — terugkijkperiode
- `months=0` — MAX (bijv. BTC terug tot 2017, ~70k candles)
- `interval=1h/4h/1d` — candle interval
- `signal_filter=PERFECT_DAY/BREAKOUT_BULL/MOMENTUM/BUY` — filter op signaaltype

#### Authenticatie
Twee methoden:
1. **Static API key:** `X-API-KEY: <CONTROL_API_TOKEN>` header
2. **Session token:** OTP via Telegram → 24u geldig token in SQLite

---

### 3. dashboard — Live UI
**Poort:** `0.0.0.0:3000`
**Bestand:** `dashboard/index.html`

**Kaarten:**
- 📊 **Coin Overzicht** — prijs, signaal, RSI, Kimi redenering
- ⚙️ **Systeem** — mode, exchange, Kimi/Agent tijden
- ⚡ **Flash Crash Detector** — recente crashes
- 🤖 **AI Agent Workflow** — Research→Strategy→Risk→Verify verdict
- 💰 **Demo Account** — orders, volume, win-rate, gem. P&L
- 📈 **Signaal Performance** — wat hadden signalen opgeleverd (15m/1u/4u)
- 🔬 **Historische Backtest** — dropdown (40+ coins), periode, signaalfilter

**Inloggen:**
- Ga naar `http://<server>:3000` → automatisch doorgestuurd naar `login.html`
- Vul emailadres in → code via Telegram → 24u sessie

---

### 4. Database (SQLite)
**Pad:** `/var/apex/apex.db` (gedeeld via Docker volume `apex_data`)

| Tabel | Beschrijving |
|-------|--------------|
| `events` | Alle log events (info/warning/error) |
| `orders` | Geplaatste orders (executor, symbol, side, size, price) |
| `signal_performance` | Live signalen + P&L na 15m/1u/4u |
| `historical_backtest` | Historische backtest resultaten per signaal |
| `otp_codes` | Telegram OTP codes (10 min geldig) |
| `sessions` | Login sessie tokens (24u geldig) |
| `proposals` | AI agent proposals |

---

## Installatie

### Vereisten
- Ubuntu 22.04 / 24.04
- Docker + Docker Compose
- Poorten 8080 en 3000 open in firewall

### Stap 1: Secrets instellen
```bash
cp secrets/apex.env.example secrets/apex.env
cp secrets/control_api.env.example secrets/control_api.env
# Vul in:
# secrets/apex.env       → BLOFIN_API_KEY, BLOFIN_API_SECRET, BLOFIN_API_PASSPHRASE
# secrets/control_api.env → CONTROL_API_TOKEN, TG_BOT_TOKEN_COORDINATOR, TG_CHAT_ID, ALLOWED_EMAILS
```

### Stap 2: Starten
```bash
chmod +x install.sh
./install.sh
# OF handmatig:
docker compose up -d --build
```

### Stap 3: Dashboard openen
Ga naar: `http://<server-ip>:3000`

---

## Secrets Configuratie

### `secrets/apex.env`
```env
BLOFIN_API_KEY=...
BLOFIN_API_SECRET=...
BLOFIN_API_PASSPHRASE=...
SYMBOL=XRP-USDT
TRADING_MODE=demo
EXECUTOR_MODE=blofin_demo
KIMI_API_KEY=...
```

### `secrets/control_api.env`
```env
CONTROL_API_TOKEN=<sterk-wachtwoord>
TG_BOT_TOKEN_COORDINATOR=<telegram-bot-token>
TG_CHAT_ID=<jouw-telegram-chat-id>
ALLOWED_EMAILS=jouw@email.com
```

---

## AI Agent Workflow

Elke 30 minuten draait de volledige agent pipeline:

```
1. Researcher Agent
   → Analyseert coin states + historische backtest resultaten
   → Geeft: analyse, kansen, risico's, backtest_inzicht

2. Strategy Agent
   → Op basis van research: concrete entry/exit regels
   → Geeft: strategy, entry, exit, position_size_pct, stoploss_pct

3. Risk Auditor Agent
   → Beoordeelt strategie op risico
   → Geeft: goedgekeurd, reden, aanbevelingen

4. Verification Agent
   → Finale GO/NO_GO beslissing
   → Geeft: beslissing, vertrouwen_pct, samenvatting
```

Alle agents gebruiken **Kimi K2.5** via NVIDIA API.

---

## Historische Backtest

De backtest engine haalt data op van Binance en draait alle 5 strategieën erover.

**Resultaten per signaal:**
- Hoeveel keer gevonden
- Win-rate na 1u / 4u / 24u
- Gemiddelde P&L na 1u / 4u / 24u
- Beste / slechtste resultaat
- Profit factor

**Via dashboard:** Selecteer coin → periode → optioneel signaalfilter → Start Backtest

**Via API:**
```bash
# BTC afgelopen 6 maanden
curl -H "X-API-KEY: token" http://localhost:8080/backtest/historical/BTCUSDT?months=6

# XRP alles beschikbaar
curl -H "X-API-KEY: token" http://localhost:8080/backtest/historical/XRPUSDT?months=0

# Alleen PERFECT_DAY signalen
curl -H "X-API-KEY: token" "http://localhost:8080/backtest/historical/XRPUSDT/signals?months=6&signal_filter=PERFECT_DAY"
```

---

## Guardrails

Het platform heeft ingebouwde veiligheidslimieten:
- `TRADING_MODE` moet altijd `demo` zijn
- `EXECUTOR_MODE` moet altijd `blofin_demo` zijn
- `ALLOW_LIVE` moet altijd `false` zijn

→ Afwijking gooit een RuntimeError bij opstart.

---

## Poorten

| Service | Poort | Publiek |
|---------|-------|---------|
| control_api | 8080 | Ja (beveiligd via token/sessie) |
| dashboard | 3000 | Ja (vereist Telegram login) |

---

## Telegram Bots

| Bot | Beschrijving |
|-----|--------------|
| CoordinatorBot | Stuurt login OTP codes + trading alerts |
| DiscussBot | Commando's via chat (`/apply`, etc.) |

---

*Demo platform — geen garantie voor toekomstige resultaten.*
