# OpenClaw Apex — AI Crypto Trading Platform v2

> Full-stack algorithmic crypto trading platform with live signal detection, setup scoring, near-miss monitoring, interactive charts, and an autonomous AI operator. Runs in **paper trading mode by default** (BloFin demo) — live trading on BloFin is supported and can be enabled.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status: Paper Trading](https://img.shields.io/badge/Status-Paper%20%26%20Live%20Ready-orange)]()

---

## What is this?

OpenClaw Apex is a full-stack **algorithmic crypto trading platform** with an autonomous AI operator at its core.

1. **Tracks 40 coins** in real-time via Binance WebSocket kline feeds — live OHLCV per symbol
2. **Scores every (coin × signal) setup** using historical OHLCV data — P1 scoring with STERK / TOESTAAN / TOESTAAN_ZWAK / SKIP verdicts
3. **Detects live signals** — RSI, MACD, ADX, EMA regime, Bollinger Bands per coin, updated every minute
4. **Near-miss monitoring** — logs events that almost triggered but failed a guard (volume, BTC threshold, etc.) with full diagnostic metadata
5. **Runs a paper trading testbot** — buys only `STERK` setups, tracks TP/SL/TIMEOUT outcomes in PostgreSQL
6. **Visualises everything** — interactive candlestick charts with historical setup markers and bot trade markers overlaid
7. **AI operator (Jojo1)** — autonomous AI runs 24/7 inside the `openclaw_gateway` container, accessible via Telegram

---

## Jojo1 — The AI Operator

**Jojo1 is the brain of the platform.** It is not a chatbot — it is an autonomous operator that runs 24/7 inside the `openclaw_gateway` container.

Jojo1 has full access to all platform data and uses it independently:

| What Jojo1 does | How |
|-----------------|-----|
| Reads live signals + indicator values | Queries `indicator_engine` and `control_api` |
| Analyzes historical patterns | Uses `jojo_analytics` + historical context database |
| Evaluates setup quality (P1 scores) | Reads STERK/TOESTAAN verdicts per coin × signal |
| Monitors macro conditions | Uses `market_oracle_sandbox` (RSS + Yahoo Finance) |
| Pauses trading on danger signals | Auto-pause on high crash score — no human needed |
| Proposes parameter changes | Submits proposals via the Gatekeeper API |
| Sends market reports every 30 minutes | Via `tg_coordinator_bot` to Telegram |
| Responds to questions via Telegram | Owner can ask anything about current market state |
| Triggers Kimi pattern fallback | Calls `kimi_pattern_agent` on major/extreme near-miss events |

### How the owner interacts

The platform runs **fully autonomously**. The owner only needs to act when they want to:

```
Owner sends Telegram message to Jojo1:
  "analyze current market and suggest better stoploss if needed"

Jojo1:
  1. Reads live signals for all 40 coins
  2. Checks P1 scores + recent win rates
  3. Runs a backtest if needed
  4. Submits a proposal: "change stoploss from 2.0% to 2.5%"
  5. Sends OTP to Telegram: "Confirm with /ok abc123"

Owner replies: /ok abc123
  → Parameter applied, trading continues
```

### Safety: the Gatekeeper

Jojo1 cannot do anything dangerous on its own. Every action goes through the **Gatekeeper**:

- All parameter changes require **OTP confirmation** from the owner via Telegram
- Trading can only be paused/resumed — Jojo1 cannot open positions directly
- `ALLOW_LIVE` can never be set by Jojo1 — hardcoded block
- All actions are logged in the audit trail
- `PARAM_BOUNDS` enforced server-side on all configurable parameters

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                  Docker Compose (VPS — 4 CPU / 8 GB RAM)            │
│                                                                     │
│  command_center      :4000  ←── Auth proxy + web UI (6 pages)      │
│  control_api         :8080  ←── FastAPI (30+ endpoints, testbot)   │
│  postgres            :5432  ←── PostgreSQL 16 (18+ tables)         │
│  indicator_engine    :8099  ←── TA engine, 40 coins WS, near-miss  │
│  jojo_analytics      :8097  ←── Performance + trade features API   │
│  kimi_pattern_agent  :8098  ←── Nightly pattern analysis (03:00)   │
│  market_oracle_sandbox:8095 ←── RSS + Yahoo Finance macro feed     │
│  apex_engine                ←── Trading engine (signals, orders)   │
│  openclaw_gateway           ←── Jojo1 AI (Telegram @franstest1_bot)│
│  tg_coordinator_bot         ←── 30-min market reports to Telegram  │
│  tg_discuss_bot             ←── Kimi AI interactive chat bot       │
│  dashboard           :3000  ←── Nginx (6 HTML pages)              │
│  mcp_server          :8100  ←── FastMCP (optional, off by default) │
│  cloudflare_tunnel          ←── HTTPS for MCP (optional)           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 40 Tracked Coins

```
BTC  ETH  SOL  AAVE AVAX LINK DOT  UNI  LTC  DOGE
XRP  BNB  ADA  ATOM ARB  APT  SEI  SUI  TRX  NEAR
BCH  ICP  HBAR PEPE WIF  WLD  ENA  TAO  ZEC  OP
XLM  SHIB FET  BONK FLOKI RENDER INJ TIA  ALGO VET
```

Universe is managed dynamically via CoinGecko Top-50 + Binance USDT spot validation. Invalid/delisted coins are automatically filtered and deactivated.

---

## P1 Setup Scoring System

The **setup judge** scores every `(coin × signal_type)` combination using available OHLCV history:

```
Score (0–100):
  Win rate    0–40 pts  ← % of trades profitable after 1h
  Avg PnL     0–30 pts  ← mean 1h return across all occurrences
  Sample size 0–15 pts  ← min 10 trades required, bonus at n ≥ 100
  Regime      0–15 pts  ← bonus if signal performs better in current BTC regime

Verdict thresholds:
  STERK         score ≥ 70  AND  win% ≥ 55%  AND  avg_pnl ≥ 0.20%  AND  n ≥ 20
  TOESTAAN      score ≥ 50
  TOESTAAN_ZWAK score ≥ 30
  SKIP          below thresholds or negative edge
```

Example output (DOGE / BREAKOUT_BULL):
```
score=78  win%=83.3  avg_1h=+0.785%  n=30 → STERK
```

---

## Signal Types Detected

| Signal | Trigger conditions |
|--------|--------------------|
| `BREAKOUT_BULL` | Price > upper Bollinger Band + RSI > 50 + volume > 1.5× avg |
| `MOMENTUM` | EMA21 > EMA55 > EMA200 + RSI 50–65 + MACD bullish + ADX > 25 |
| `BUY` | RSI < 32 + MACD turning up, or StochRSI oversold (k < 20, k > d) |
| `PERFECT_DAY` | All of the above simultaneously |

---

## Near-Miss Monitoring (P2)

The platform logs **near-miss events** — situations where a signal almost fired but was blocked by a guard condition. This gives operators visibility into why alerts did NOT trigger.

```
Near-miss types:
  btc_drop_nearmiss   BTC dropped -0.6% to -0.7%/60s (below major threshold)
  drop_vol_guard      Drop detected but volume surge guard not met (vol_ratio < 1.5×)
  near_major_drop     Drop reached ≥80% of major threshold but didn't cross it

BTC dedicated detection path:
  Major alert:   BTC Δ ≥ -0.7%/60s  →  fires WITHOUT volume requirement
  Extreme alert: BTC Δ ≥ -1.2%/90s  →  escalates to panic mode

Kimi fallback:
  On major/extreme near-miss for BTC/ETH/SOL/XRP/BNB → kimi_pattern_agent called
  3-minute cooldown per symbol, Telegram-ready alert format
```

**Endpoints:**
- `GET /alerts/near-miss` — filter by symbol, event_kind, failed_guard, severity
- `GET /validation/p2-summary?hours=24` — KPI Gate Matrix (missed drops, false alerts, detect delay, fallback spam)
- `POST /tuning/suggest` — profile-based threshold suggestions (safe / balanced / aggressive)

---

## Dashboard Pages

| Page | What you see |
|------|-------------|
| **⚡ Live Signals** | Real-time RSI/MACD/ADX per coin, signal type, P1 verdict, operator strip (near-miss / WS reliability / Kimi fallback / KPI matrix) |
| **📊 Setup Intelligence** | Historical quality of each (coin × signal) setup, last signal timestamp, plain-language interpretation |
| **📈 Chart** | Candlestick + EMAs + 3 marker types: Setup Intel moments, bot buy entries, bot exit (TP/SL/TIMEOUT) |
| **🤖 Bot Positions** | Open paper trades with live Binance price, TP/SL progress bar, slot counter, recent closed trades |
| **📉 STERK Quality** | Closed paper trade analysis — cumulative PnL chart, daily breakdown, CSV export, plain-language summary |
| **🏠 Home** | System overview — mode, crash score, universe status, short status |

### Operator Strip (Live Signals page)

The bottom of the Live Signals dashboard shows three always-visible blocks:

- **"Why no alert?"** — last 3 near-misses with failed guard, Δ60s, age
- **"Live reliability"** — per-symbol WS stale dots (green/yellow/red) + global WS status + KPI Gate matrix
- **"Kimi fallback"** — recent major near-miss events for top-5 coins with cooldown countdown

---

## Paper Trading Testbot

Runs as a background thread inside `control_api`. **No live trading — BloFin demo only.**

| Parameter | Value |
|-----------|-------|
| Entry condition | `STERK` verdict only |
| Stake per trade | $100 USD |
| Max concurrent trades | configurable (default 3, max 6) |
| Take Profit | +4.5% |
| Stop Loss | −2.0% |
| Max duration | 2 hours (TIMEOUT) |
| Fee (round-trip) | 0.2% |
| Live price source | Binance public API |
| Storage | PostgreSQL `demo_account` |

Tracks price snapshots at 15m / 1h / 2h after entry for detailed outcome analysis. `trade_features` table stores indicator snapshot at entry for each trade.

---

## Sniper Bot

The indicator_engine includes a built-in **Sniper Bot** — configurable alert triggers for precise market events.

| Mode | Description |
|------|-------------|
| `dip` | Alert when price dips to a target level |
| `short` | Alert on bearish signal matching conditions |
| `breakout` | Alert on breakout above resistance level |
| `niveau` | Alert when price reaches a specific price level |

Snipers run every 60s inside indicator_engine. Create/manage via Telegram commands (`/sniper ...`) through `tg_discuss_bot`.

---

## Apex Engine Filters (in order)

Every potential trade signal passes through 10 sequential filters before execution:

1. Trading halt check
2. Skip coins (via config overrides)
3. BTC EMA200 filter (4h) — blocks longs when BTC is below EMA200
4. BTC EMA21/55 filter (1h)
5. Pre-crash score ≥ 60
6. RSI < rsi_buy_threshold (default 30)
7. RSI chop zone block (rsi_threshold < RSI < rsi_chop_max, default 55)
8. Signal blacklist
9. Pattern engine (1h + 4h Kimi analysis)
10. Max positions check

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.11, FastAPI, uvicorn |
| Database | PostgreSQL 16 |
| DB compat layer | `db/db_compat.py` — `?`→`%s`, `datetime()`→`NOW()` |
| Charts | TradingView Lightweight Charts v4.1.3 |
| Live prices | Binance WebSocket kline streams (40 symbols) + public REST API |
| Auth | Telegram OTP login + session tokens |
| AI operator | Jojo1 — autonomous operator via openclaw_gateway (OpenAI) |
| Pattern AI | Kimi (Moonshot AI) — nightly + fallback analysis |
| Infrastructure | Docker Compose, Nginx, Cloudflare tunnel |
| Exchange | BloFin Demo (paper trading) / BloFin Live (optional) |

---

## Database Tables (PostgreSQL)

```sql
ohlcv_data           -- OHLCV candles per coin/interval
indicators_data      -- RSI, MACD, EMA21/55/200, ADX, BB, StochRSI per candle
historical_context   -- signal occurrences + future 1h/4h/24h PnL outcomes
crash_score_log      -- market crash probability score over time
demo_account         -- paper trade log (entry, exit, TP/SL/TIMEOUT, PnL, fees)
trade_features       -- indicator snapshot at entry per trade (linked to demo_account)
events               -- audit trail: bot OPEN/CLOSE events with full payload
signal_context       -- latest live signals from apex_engine
universe_coins       -- active coin list (CoinGecko + Binance spot validated)
mode_log             -- trading mode history (normal/panic/crash + reason)
alerts               -- high-impact alerts log (drop, spike, depeg)
near_miss_log        -- near-miss events log (failed guards, deltas, severity)
config_overrides     -- per-coin config overrides (skip, stoploss, etc.)
short_log            -- short position log
apex_proposals       -- Gatekeeper: pending parameter change proposals
otp_sessions         -- OTP login tokens (6-digit, 10 min expiry)
sniper_targets       -- active sniper bot targets
```

---

## Key API Endpoints

```http
# Indicator engine (port 8099)
GET  /indicators/{symbol}               live TA values + signal for one coin
GET  /alerts/high-impact                high-impact drop/spike/depeg alerts
GET  /alerts/near-miss                  near-miss log (filter: symbol, event_kind, failed_guard)
GET  /validation/p2-summary?hours=24    KPI Gate Matrix (24h detection quality metrics)
POST /tuning/suggest                    threshold suggestions based on profile
GET  /universe/current                  active coin list + metadata
POST /universe/refresh                  trigger manual universe refresh
GET  /mode/current                      current trading mode (normal/panic/crash)
POST /mode/set                          set mode manually
GET  /sniper/list                       active sniper targets
POST /sniper/set                        create sniper target

# Control API (port 8080, auth required via command_center :4000)
GET  /live/signals                      current indicators + signal + P1 verdict per coin
GET  /setup/scan                        P1 score all coins × signals
GET  /testbot/status                    bot state + config + all-time stats
GET  /testbot/positions                 open positions with live price + current PnL
GET  /testbot/history?limit=100         closed trades with outcome breakdown
POST /testbot/start | /testbot/stop     start or stop the bot
GET  /signal/explain?symbol=X&signal=Y  filter-stack explanation per coin+signal

# Analytics (port 8097)
GET  /performance/unified               PnL per coin/signal/regime
GET  /features/{trade_id}              indicator snapshot for one trade
GET  /features-summary                 aggregated features per regime/signal/RSI band
```

---

## Project Structure

```
.
├── control_api/
│   └── app/
│       ├── server.py            # FastAPI — 30+ endpoints, auth, Gatekeeper, testbot
│       └── testbot.py           # Paper trading bot — background thread
├── indicator_engine/
│   ├── server.py                # TA engine, WS feeds, near-miss, spike monitor, universe
│   └── universe_manager.py     # CoinGecko + Binance spot validation + DB sync
├── command_center/
│   └── app/server.py           # Auth proxy + all /cc/* proxy routes
├── kimi_pattern_agent/
│   └── server.py               # Moonshot Kimi API + nightly analysis + /fallback-alert
├── jojo_analytics/
│   └── server.py               # Trade features, performance, unified PnL
├── apex_engine/                 # Trading engine — signal evaluation + order logic
├── dashboard/
│   ├── live_signals.html        # ⚡ Real-time signals + operator strip
│   ├── setup_intelligence.html  # 📊 Historical setup quality
│   ├── chart.html               # 📈 Chart with 3 marker types
│   ├── bot_positions.html       # 🤖 Open paper positions
│   ├── sterk_quality.html       # 📉 Closed trade analysis
│   └── index.html               # Dashboard home
├── db/
│   ├── init.sql                 # PostgreSQL schema (18+ tables + indices)
│   └── db_compat.py             # SQLite ↔ PostgreSQL compatibility layer
├── docs/
│   └── PLATFORM_INFO.md         # Full system documentation
├── secrets/                     # *.env files — NEVER committed
├── docker-compose.yml
└── README.md
```

---

## Installation

```bash
git clone https://github.com/Frans1979valk/openclaw-apex-v2.git
cd openclaw-apex-v2
cp secrets/*.env.example secrets/*.env   # fill in your API keys
docker compose up -d
# → open http://your-vps-ip:4000
```

**Required secrets:**
- `secrets/postgres.env` — `POSTGRES_PASSWORD`, `DATABASE_URL`
- `secrets/apex.env` — BloFin API keys, `ALLOW_LIVE`, trading parameters
- `secrets/openclaw_gateway.env` — AI operator API key + `TG_BOT_TOKEN`
- `secrets/tg.env` — Telegram bot tokens for coordinator + discuss bot

---

## Security

- Dashboard protected by **Telegram OTP** — login sends 6-digit code to your Telegram
- All API endpoints require `X-API-KEY` header (via command_center auth)
- Session tokens expire after 24 hours
- Secrets in `secrets/*.env` — gitignored, never pushed
- HTTPS via Cloudflare tunnel or self-signed certificate
- Gatekeeper enforces `PARAM_BOUNDS` on all configurable parameters

---

## Current Status

| Feature | Status |
|---------|--------|
| P1 setup scoring engine | ✅ Live |
| Live signals dashboard (40 coins) | ✅ Live |
| Interactive charts + markers | ✅ Live |
| Paper trading testbot | ✅ Running (test phase) |
| Setup Intelligence page | ✅ Live |
| Near-miss monitoring + logging | ✅ Live |
| KPI Gate Matrix + validation endpoint | ✅ Live |
| Tuning suggest endpoint | ✅ Live |
| Dashboard operator strip | ✅ Live |
| Sniper Bot | ✅ Live |
| Universe manager (CoinGecko + Binance) | ✅ Live |
| Kimi nightly pattern analysis | ✅ Live (03:00 UTC) |
| Kimi fallback on major near-miss | ✅ Live |
| Short signals | ✅ Supported |
| Real money trading | ⚙️ Supported — disabled by default |

---

## Live Trading (optional)

The platform is designed for **paper trading by default**, but live trading on BloFin is supported.

To enable live trading:

1. Set `ALLOW_LIVE=true` in `secrets/apex.env`
2. Replace the BloFin demo API keys with your **live account** API keys
3. Restart the engine: `docker compose restart apex_engine`

> **Warning:** Live trading uses real money. The platform is still in test phase. Use at your own risk. Start with small position sizes and monitor closely. The authors are not responsible for financial losses.

All safety mechanisms (Gatekeeper, PARAM_BOUNDS, OTP confirmation, trading halt) remain active in live mode.

---

## License

MIT — free to use, study and build upon. Not financial advice.

---

*Built with Claude Code. Near-miss monitoring, universe validation and operator strip added 2026-03-09.*
