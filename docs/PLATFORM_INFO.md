# OpenClaw Apex Trading Platform — Volledige Documentatie

**Versie:** 2.0 (2026-03-07)
**Status:** Live op VPS, demo trading mode (BloFin paper account)

---

## 1. Wat is dit systeem?

Een volledig autonome AI crypto trading platform bestaande uit 16 Docker containers. Het platform **werkt volledig automatisch — zonder handmatige tussenkomst van Frans**. Het:
- Selecteert automatisch de beste coins via AI (Kimi)
- Analyseert marktdata met technische indicatoren (4 jaar historische data)
- Plaatst virtuele trades (demo mode — geen echt geld)
- Leert van eigen trades en optimaliseert parameters
- Bewaakt de markt via Telegram bots
- Stuurt alerts en rapportages naar Telegram

**Eigenaar:** Frans
**AI Operator:** Jojo1 (draait in `openclaw_gateway` container, Claude Sonnet 4.6)
**Platform taal:** Nederlands (Telegram), Python (services), TypeScript (gateway)

---

## 1b. OpenClaw — Het Masterframework (Ruggengraat)

**OpenClaw is het hart van het platform.** Het is een TypeScript-gebaseerd agent runtime framework dat het platform volledig autonoom laat werken — **helemaal zonder dat Frans iets hoeft te doen**.

### Wat OpenClaw doet

OpenClaw draait als `openclaw_gateway` container en is de enige component die alle andere services coördineert:

| Functie | Beschrijving |
|---------|--------------|
| **AI motor** | Claude Sonnet 4.6 als taalmodel — begrijpt marktdata, neemt beslissingen |
| **Tool systeem** | Python scripts aanroepen: indicator_engine, control_api, sniper, markt data |
| **Skill systeem** | Complexe workflows (analyse, rapport, strategie) als herbruikbare skills |
| **Multi-agent** | Sub-agents aansturen: Research Agent, Risk Agent voor diepere analyses |
| **Telegram** | Primair communicatiekanaal — ontvangt vragen, stuurt alerts en rapporten |
| **Persistent memory** | Onthoudt context, beslissingen en leereffecten over sessies heen |
| **Collab systeem** | Inbox-gebaseerde communicatie met Dev (Claude Code) voor updates |

### Autonome werking (zonder Frans)

Het platform draait 24/7 volledig autonoom:

```
[apex_engine] — Elke 10s: analyseert 40 coins, plaatst demo orders
     ↑
[indicator_engine] — Levert TA-data (RSI, MACD, EMA, Sniper monitoring)
     ↑
[tg_coordinator_bot] — Elke 30min: marktrapport naar Telegram
     ↑
[kimi_pattern_agent] — Elke nacht 03:00: patroonanalyse op historische data
     ↑
[openclaw_gateway / Jojo1] — Coördineert alles, reageert op events
```

### Jojo1 als autonome operator

Jojo1 is **geen chatbot** — het is een autonome operator die zelfstandig:
1. Marktdata opvraagt en interpreteert
2. Configuraties aanpast via het proposals systeem
3. Snipers instelt bij gunstige condities
4. Trading pauzeert bij gevaar (pre-crash signalen)
5. Frans informeert via Telegram wanneer actie relevant is

Frans hoeft alleen in te grijpen als hij dat **zelf wil** — het systeem beslist autonoom.

### OpenClaw vs. de andere services

```
OpenClaw (master/brein)
    ├── apex_engine        → voert trades uit (slaaf van config)
    ├── indicator_engine   → levert data (slaaf van queries)
    ├── control_api        → beheert config (slaaf van proposals)
    ├── tg_discuss_bot     → Kimi marktchat (onafhankelijk)
    └── alle andere svcs   → ondersteunende roles
```

**OpenClaw is de enige component die nadenkt. De rest voert uit.**

---

## 2. Container Architectuur

```
┌─────────────────────────────────────────────────────────────────────┐
│                         agent_net (intern)                          │
│                                                                     │
│  ┌──────────────────┐      ┌─────────────────┐                     │
│  │  openclaw_gateway │      │   control_api    │                    │
│  │  (Jojo1 brain)   │─────▶│   :8080 REST     │                    │
│  │  Claude 4.6      │      │   PostgreSQL     │                    │
│  └──────────────────┘      └────────┬────────┘                     │
│                                     │                               │
│  ┌──────────────────┐      ┌────────▼────────┐                     │
│  │  indicator_engine │      │   apex_engine    │                    │
│  │  :8099 TA+4yr    │◀────▶│   Trading loop   │                    │
│  │  40 coins        │      │   BloFin Demo    │                    │
│  └──────────────────┘      └─────────────────┘                     │
│                                                                     │
│  ┌──────────────────┐      ┌─────────────────┐                     │
│  │  tg_discuss_bot  │      │  tg_coordinator  │                    │
│  │  Kimi chat       │      │  30min rapporten │                    │
│  │  @franscrypto    │      │  @franstest1     │                    │
│  └──────────────────┘      └─────────────────┘                     │
│                                                                     │
│  ┌──────────────────┐      ┌─────────────────┐                     │
│  │  command_center  │      │  jojo_analytics  │                    │
│  │  :4000 Web UI    │      │  :8097 TA query  │                    │
│  └──────────────────┘      └─────────────────┘                     │
│                                                                     │
│  ┌──────────────────┐      ┌─────────────────┐                     │
│  │ kimi_pattern_    │      │ market_oracle_   │                    │
│  │ agent :8098      │      │ sandbox :8095    │                    │
│  │ Nachtanalyse     │      │ RSS + Yahoo      │                    │
│  └──────────────────┘      └─────────────────┘                     │
│                                                                     │
│  ┌──────────────────┐      ┌─────────────────┐                     │
│  │   mcp_server     │      │ cloudflare_      │                    │
│  │   :8100 (UIT)    │      │ tunnel (UIT)     │                    │
│  └──────────────────┘      └─────────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────┐
│                         trade_net (intern)                          │
│   postgres :5432   ←→   apex_engine   ←→   indicator_engine        │
│   control_api                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Alle Services

### 3.1 apex_engine
**Rol:** Hoofd trading engine — draait een eindeloze loop die elke 10 seconden markten analyseert

**Wat het doet:**
1. Elke 5 minuten: Kimi selecteert beste coins uit top 30 movers
2. Voor elke coin berekent het: RSI, MACD, EMA's, ADX, Bollinger Bands, pre-crash score
3. Meerdere AI-filters beslissen of een trade uitgevoerd wordt
4. Plaatst virtuele demo trades op BloFin paper account

**Filters (in volgorde):**
1. **Trading halt check** — gestopt als `trading_halt.json` halt=true heeft
2. **Skip coins** — configureerbaar via `skip_coins` proposal
3. **BTC EMA200 filter (4h)** — geen longs als BTC prijs < EMA200 op 4h timeframe
4. **BTC EMA21/55 filter (1h)** — geen altcoin longs als BTC bearish (EMA21<EMA55 + RSI<45)
5. **Pre-crash score** — geblokkeerd als score ≥ 60/100
6. **RSI filter** — RSI moet onder drempel (default 30) zijn
7. **RSI chop zone** — geen BUY als RSI tussen `rsi_buy_threshold` en `rsi_chop_max` (30-55)
8. **Signal blacklist** — blokkeert (coin, signal) combos met structureel slechte historische PnL
9. **Pattern engine filter** — 1h + 4h bevestiging vereist, AVOID signaal blokkeert
10. **Max posities** — default 4 gelijktijdige open posities
11. **Order cooldown** — 120 seconden tussen orders per coin

**Config (aanpasbaar via proposals):**
```json
{
  "rsi_buy_threshold": 30,
  "rsi_chop_max": 55,
  "stoploss_pct": 2.0,
  "takeprofit_pct": 4.5,
  "max_positions": 4,
  "skip_coins": ["DOTUSDT", "UNIUSDT"],
  "pattern_min_confidence": 0.0
}
```

**Bestand:** `apex_engine/app/main.py`

---

### 3.2 control_api
**Rol:** REST API — centrale hub voor data, config en commando's
**Poort:** 8080 (intern)

**Endpoints:**
- `GET /balance` — demo account balans, P&L, win rate
- `GET /state/latest` — actuele staat van alle gevolgde coins
- `GET /orders` — recente trades
- `GET /signal-performance` — win rate per coin+signaal
- `POST /config/propose` — stel parameterwijziging voor
- `POST /proposals/{id}/apply` — activeer een proposal
- `GET /proposals` — bekijk openstaande voorstellen
- `POST /trading/halt` / `/resume` / `/pause` — trading beheer
- `GET /trading/status` — huidige trading status

**Auth:** `X-API-KEY` header (token in `secrets/control_api.env`)

**Bestand:** `control_api/app/server.py`

---

### 3.3 indicator_engine
**Rol:** Historische data opslag + technische analyse + sniper bot
**Poort:** 8099 (intern)

**Data:**
- 40 coins × 12 maanden × 1h + 4h interval = ~1,4 miljoen OHLCV candles
- Indicatoren: RSI, MACD, EMA21/55/200, Bollinger Bands, ADX, StochRSI, ATR, Volume ratio
- Patroon matching: welke RSI/MACD combinaties hebben historisch de beste resultaten
- Elke uur automatisch bijgewerkt voor alle 40 coins

**Endpoints:**
- `GET /signal/{symbol}?interval=1h` — signaal + precedenten + confidence
- `GET /indicators/{symbol}?interval=1h` — huidige TA indicators incl. ema200, close
- `GET /patterns/{symbol}` — alle patroon-precedenten gesorteerd op win rate
- `GET /coverage` — welke coins/intervals aanwezig zijn
- `GET /top-coins?limit=20` — top coins op 24h volume
- `POST /backtest/strategy` — strategie backtest op 4 jaar data
- `POST /reverse-backtest` — reverse backtest: vindt pre-crash fingerprints
- `POST /import` — historische data importeren (achtergrond)
- `POST /sniper/set` — nieuwe sniper instellen
- `GET /sniper/list` — actieve snipers
- `DELETE /sniper/{id}` — sniper annuleren

**40 Coins:**
BTC, ETH, SOL, AAVE, AVAX, LINK, DOT, UNI, LTC, DOGE, XRP, BNB, ADA, ATOM, ARB, APT, SEI,
SUI, TRX, NEAR, BCH, ICP, HBAR, PEPE, WIF, WLD, ENA, TAO, ZEC, OP,
XLM, SHIB, FET, BONK, FLOKI, RENDER, INJ, TIA, ALGO, VET

**Bestand:** `indicator_engine/server.py`

---

### 3.4 Sniper Bot (onderdeel van indicator_engine)

**Modes:**
- `dip` — wacht tot RSI < drempel (default 28) + volume daalt
- `short` — wacht tot RSI > drempel (default 68) + MACD negatief
- `breakout` — wacht tot RSI 50-65 + volume spike + EMA bullish
- `niveau` — wacht tot prijs een niveau bereikt

**Gebruik via Telegram (@franscryptoinlog_bot):**
```
/sniper dip BTC              → wacht op RSI < 28
/sniper dip BTC rsi=25       → aangepaste drempel
/sniper short ETH rsi=68     → short entry wachten
/sniper niveau BTC target=80000 direction=dip
/sniper list                 → actieve snipers
/sniper cancel <id>          → annuleer
/sniper reverse BTC          → reverse backtest crash analyse
```

**Gebruik door Jojo1 (tool):**
```bash
python3 /workspace/tools/tool_sniper.py set dip BTCUSDT rsi=28
python3 /workspace/tools/tool_sniper.py list
python3 /workspace/tools/tool_sniper.py cancel <id>
python3 /workspace/tools/tool_sniper.py reverse BTCUSDT threshold=-5
```

**Alert bij trigger (Telegram):**
```
🎯 SNIPER TRIGGER: BTCUSDT DIP
RSI: 24.5 (drempel: 28)
Prijs: $67.400
MACD hist: -120.4
✅ Optimaal koopmoment — kies zelf je entry
```

---

### 3.5 Reverse Backtest

**Concept:** Omgekeerd backtesten — identificeert grote crashes/dalingen en analyseert welke signalen er van tevoren aanwezig waren. Bouwt een "pre-crash fingerprint".

**Endpoint:** `POST /reverse-backtest`
```json
{
  "symbol": "BTCUSDT",
  "crash_threshold_pct": -5,
  "lookback_hours": [1, 4, 8, 24],
  "interval": "1h"
}
```

**Resultaat (BTCUSDT, echte data):**
- 1105 crash events gevonden (crashes ≤ -5%)
- Beste predictor: `ema_bull_false op T-1h` (aanwezig in 95% van crashes)
- Pre-crash fingerprint: rsi_below_35 + macd_negative + ema_bull_false op T-1h, T-4h, T-8h

---

### 3.6 openclaw_gateway (Jojo1)
**Rol:** AI operator — Jojo1's hersenen. Ontvangt Telegram berichten, denkt na, voert tools uit.
**Model:** Claude Sonnet 4.6 (Anthropic)
**Telegram:** @franstest1_bot
**Poort:** 18789 (intern)

**Jojo1 heeft toegang tot:**
- Alle tools in `/workspace/tools/`
- Skills: gatekeeper, macro_context_oracle, market_oracle
- Control API (trading halt, status, orders)
- Indicator engine (signals, patterns, sniper)

**Belangrijk:** Vereist Anthropic API credits. Key staat in `secrets/openclaw_gateway.env`.

**Chat logs:** Opgeslagen in Docker volume `openclaw_logs` → `/tmp/openclaw/openclaw-DATUM.log`

---

### 3.7 tg_discuss_bot (Kimi chat)
**Rol:** Tweede Telegram bot voor marktanalyse via Kimi AI
**Model:** moonshot-v1-32k (Moonshot AI / Kimi)
**Telegram:** @franscryptoinlog_bot

**Commando's:**
```
/status          — marktoverzicht
/balance         — demo balans
/coins           — gevolgde coins
/perf            — signal performance
/patroon BTC     — historische patroonanalyse
/signal ETH 4h   — indicator signaal + precedenten
/backtest BTC    — strategie backtest
/sniper dip BTC  — sniper instellen
/sniper list     — actieve snipers
/sniper reverse BTC — crash analyse
/stop            — NOODSTOP trading
/start           — hervat trading
/pauzeer 30      — pauzeer 30 minuten
/zoek query      — DuckDuckGo zoeken
```

**Bestand:** `telegram/discuss_bot/bot.py`

---

### 3.8 tg_coordinator_bot
**Rol:** Stuurt elke 30 minuten een marktrapport naar Telegram
**Telegram:** @franstest1_bot (zelfde kanaal als Jojo1 of aparte groep)

**Rapportformat:**
- Coin overzicht met prijs, RSI, signaal
- Demo balans en P&L
- Pre-crash scores
- Agent workflow resultaten

---

### 3.9 command_center
**Rol:** Beveiligde webinterface voor beheer
**Poort:** 4000 (intern, via reverse proxy)
**Auth:** Telegram OTP (8 uur sessies)

**Functies:**
- Dashboard met live data
- Proposals aanmaken en goedkeuren
- Audit logging
- Proxy naar control_api

---

### 3.10 jojo_analytics
**Rol:** TA indicators + DB queries voor Jojo1 en Kimi
**Poort:** 8097 (intern)

**Endpoints:**
- `GET /analyze/{symbol}` — RSI, MACD, EMA analyse
- `GET /db/recent-trades` — recente trades uit DB
- `GET /db/signal-stats` — signaal statistieken
- `GET /oracle/news` — via market_oracle_sandbox

---

### 3.11 kimi_pattern_agent
**Rol:** Nachtelijke patroonanalyse met Kimi AI
**Poort:** 8098 (intern)
**Draait:** elke nacht om 03:00

**Doet:**
1. Haalt OHLCV data op voor BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, AAVEUSDT
2. Stuurt data naar Kimi AI voor patroonherkenning
3. Slaat rapport op in `/var/apex/pattern_report_DATUM.json`
4. Stuurt samenvatting naar Telegram

---

### 3.12 market_oracle_sandbox
**Rol:** Geïsoleerde container voor publieke marktdata
**Poort:** 8095 (intern)
**GEEN API keys** — alleen publieke RSS en Yahoo Finance

**Endpoints:**
- `GET /health`
- RSS feeds (Reuters, CoinDesk, etc.)
- Yahoo Finance quotes

---

### 3.13 mcp_server (momenteel UIT)
**Rol:** Model Context Protocol server — geeft Claude Web directe toegang tot platform
**Poort:** 8100 (intern)
**Auth:** Bearer token

**Tools beschikbaar:**
- get_balance, get_market_state, get_orders, get_signal_performance
- get_indicator_signal, get_patterns, get_data_coverage
- run_strategy_backtest, get_top_coins
- get_proposals, propose_config, apply_proposal
- trading_halt, trading_resume, trading_pause, get_trading_status

**Inschakelen:**
```bash
docker compose up -d mcp_server cloudflare_tunnel
docker logs <cloudflare_tunnel_container> | grep trycloudflare  # URL
```

---

### 3.14 cloudflare_tunnel (momenteel UIT)
**Rol:** Gratis HTTPS voor MCP server via trycloudflare.com
**Let op:** URL verandert bij elke herstart

---

### 3.15 postgres
**Rol:** PostgreSQL 16 database
**Poort:** 5432 (intern)
**Database:** `apex`

**Tabellen (17 stuks):**
- `demo_balance` — demo account balans
- `demo_account` — alle demo trades
- `signal_performance` — signalen + resultaten (open/closed)
- `market_context` — marktcontext bij signalen
- `orders` — exchange orders log
- `events` — platform event log
- `proposals` / `proposals_v2` — configuratiewijzigingen
- `backtest_results` — backtestresultaten
- `coin_approvals` — goedgekeurde coins
- `ohlcv_data` — OHLCV candles (1,4 milj. rijen)
- `indicators_data` — berekende indicators
- `pattern_results` — patroon matching resultaten
- `cc_sessions` — command center sessies
- `cc_audit` — command center audit log
- `market_snapshots` / `crash_scores` / `exchange_consensus` — data logger

---

## 4. Database Structuur

```sql
-- Demo account (virtuele trades)
demo_balance: id, balance, peak_balance, total_trades, winning_trades, total_volume_usdt
demo_account: ts, symbol, action, price, virtual_size_usdt, virtual_pnl_usdt, balance_after, signal

-- Signaal tracking
signal_performance: symbol, signal, entry_price, price_15m, price_1h, price_4h, pnl_*, status
market_context: ts, symbol, signal, rsi_5m, tf_confirm_score, tf_bias, tf_1h_rsi, tf_4h_rsi

-- Historische data (indicator_engine)
ohlcv_data: symbol, interval, ts, open, high, low, close, volume
indicators_data: symbol, interval, ts, rsi, macd_hist, bb_width, ema21/55/200, ema_bull, adx, atr, volume_ratio, rsi_zone
pattern_results: symbol, ts, interval, rsi_zone, macd_direction, pnl_1h, pnl_4h, was_win

-- Config
proposals_v2: id, ts, type, payload_json, reason, status, applied_at
```

---

## 5. Configuratie (proposals systeem)

Parameters aanpassen via proposal:

```bash
# Via control_api
curl -X POST http://localhost:8080/config/propose \
  -H "X-API-KEY: <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "Dev",
    "params": {
      "rsi_buy_threshold": 28,
      "rsi_chop_max": 55,
      "stoploss_pct": 2.0,
      "takeprofit_pct": 4.5,
      "max_positions": 3,
      "skip_coins": ["DOTUSDT", "UNIUSDT", "LINKUSDT"]
    },
    "reason": "Verbeterde filters na backtest"
  }'

# Dan toepassen:
curl -X POST http://localhost:8080/proposals/1/apply \
  -H "X-API-KEY: <token>"
```

**PARAM_BOUNDS (hardcoded limieten):**
```python
rsi_buy_threshold:  (20, 40)
rsi_chop_max:       (45, 65)
rsi_sell_threshold: (60, 80)
stoploss_pct:       (1.5, 6.0)
takeprofit_pct:     (3.0, 12.0)
position_size_base: (1, 5)
max_positions:      (1, 6)
```

---

## 6. Telegram Interface

### Bot 1: Jojo1 — @franstest1_bot
Jojo1 is de AI operator. Ze analyseert de markt, voert tools uit, stuurt alerts.
- Praat met haar via Telegram
- Ze leert van de markt en verbetert zichzelf
- **Vereist Anthropic API credits**

### Bot 2: Kimi Chat — @franscryptoinlog_bot
Snellere toegang tot marktdata via Kimi AI.
- Geen Anthropic credits nodig (gebruikt Moonshot API)
- Volledige lijst commando's: zie sectie 3.7
- Sniper bot: `/sniper dip BTC`

---

## 7. Jojo's Tools

Beschikbaar in `/workspace/tools/`:

| Tool | Functie |
|------|---------|
| `tool_intelligence.py` | Indicator signalen + patronen opvragen |
| `tool_sniper.py` | Sniper bot beheer |
| `tool_analytics.py` | TA analyse via jojo_analytics |
| `tool_run_backtest.py` | Strategie backtest uitvoeren |
| `tool_propose_params.py` | Parameterwijziging voorstellen |
| `tool_apply_proposal.py` | Proposal toepassen |
| `tool_pause_trading.py` | Trading pauzeren |
| `tool_resume_trading.py` | Trading hervatten |
| `tool_fetch_news.py` | Nieuws ophalen |
| `tool_pattern_agent.py` | Pattern agent aanroepen |
| `tool_status.py` | Platform status |

---

## 8. Collab Systeem (Dev ↔ Jojo1)

Jojo1 en de developer communiceren via bestanden:

```
openclaw_config/workspace/collab/
├── inbox/
│   ├── for_dev/        ← Jojo1 schrijft hier opdrachten voor dev
│   └── for_jojo/       ← Dev schrijft hier antwoorden voor Jojo1
├── shared/
│   ├── dev_status.md   ← Status van dev werkzaamheden
│   ├── decisions.md    ← Architectuurbeslissingen
│   └── changelog.md    ← Wijzigingslog
└── INBOX_REGELS.md     ← Spelregels voor communicatie
```

---

## 9. Deployment

```bash
# Alles starten
cd /root/openclaw_trading_platform/openclaw_trading_platform_blofin_demo_v2
docker compose up -d

# Status checken
docker compose ps

# Logs bekijken
docker compose logs -f apex_engine
docker compose logs -f indicator_engine

# Individuele service herbouwen
docker compose build <service> && docker compose up -d <service>

# MCP inschakelen
docker compose up -d mcp_server cloudflare_tunnel
docker logs ...-cloudflare_tunnel-1 2>&1 | grep trycloudflare
```

---

## 10. Veiligheidsregels (IJZEREN WETTEN)

1. `TRADING_MODE` moet altijd `demo` zijn
2. `ALLOW_LIVE` moet altijd `false` zijn
3. Max dagverlies: 5% → automatische pauze
4. Max weekverlies: 12% → trading stop
5. Jojo1 kan ALLOW_LIVE **nooit** aanpassen
6. Parameters blijven altijd binnen PARAM_BOUNDS
7. Max 3 parameterwijzigingen per dag

---

## 11. Secrets (locatie, NOOIT in git)

```
secrets/
├── apex.env           # BloFin API + Kimi key voor apex_engine
├── postgres.env       # DATABASE_URL + POSTGRES_PASSWORD
├── control_api.env    # Control API token
├── openclaw_gateway.env  # ANTHROPIC_API_KEY voor Jojo1
├── openclaw.env       # Openclaw runtime config
├── telegram_coordinator.env  # Coordinator bot token
├── telegram_discuss.env      # Kimi discuss bot token
├── command_center.env        # Command center config
└── mcp_server.env     # MCP Bearer token
```

---

## 12. Bekende Issues

1. **Jojo API credits** — Anthropic account `cryptobotbaas1` moet credits hebben voor `sk-ant-api03-0ntgy...`
2. **MCP staat UIT** — inschakelen zodra er een vaste HTTPS URL is (via Cloudflare named tunnel)
3. **apex_engine gebruikt nog geen 40 coins** — koopt alleen uit Kimi's top 5 selectie, niet uit alle 40

---

## 13. Technische Stack

| Component | Technologie |
|-----------|-------------|
| Trading engine | Python 3.12, FastAPI, TA-Lib |
| Database | PostgreSQL 16 |
| AI (apex agents) | Kimi moonshot-v1-32k |
| AI (Jojo1) | Claude Sonnet 4.6 (Anthropic) |
| AI (Kimi chat) | moonshot-v1-32k (Moonshot API) |
| Gateway (Jojo1) | OpenClaw TypeScript framework |
| Containerisatie | Docker Compose |
| Reverse proxy | Nginx |
| MCP | FastMCP 3.1 |
| HTTPS | Cloudflare Tunnel (gratis) |
| Data bron | Binance REST API (publiek) |

---

*Gegenereerd: 2026-03-07 | Repo: github.com/frans1979valk/openclaw-apex-v2*
