# OpenClaw Apex — AI Crypto Trading Platform v2

> **Paper trading** research platform with AI-driven setup scoring, live signal detection, historical backtesting, interactive charts, and an automated paper trading testbot. Built on BloFin demo mode — **no real money at risk.**

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status: Paper Trading](https://img.shields.io/badge/Status-Paper%20Trading-orange)]()

---

## What is this?

OpenClaw Apex is a full-stack **algorithmic crypto trading research platform** that:

1. **Scores every (coin × signal) setup** using 4 years of 1h OHLCV history — P1 scoring system with STERK / TOESTAAN / TOESTAAN_ZWAK / SKIP verdicts
2. **Detects live signals** in real-time — RSI, MACD, ADX, EMA regime, Bollinger Bands per coin
3. **Runs a paper trading testbot** — buys only `STERK` setups, tracks TP/SL/TIMEOUT outcomes
4. **Visualises everything** — interactive candlestick charts with historical setup markers and bot trade markers overlaid
5. **AI operator (Jojo1)** — Claude Sonnet 4.6 runs as a Telegram bot, interprets market conditions and controls the platform

---

## Screenshots / Pages

| Page | What you see |
|------|-------------|
| **⚡ Live Signals** | Real-time RSI/MACD/ADX per coin, active signal type, P1 verdict, auto-refresh every 60s |
| **📊 Setup Intelligence** | Historical quality of each (coin × signal) setup, last signal timestamp, plain-language interpretation |
| **📈 Chart** | Candlestick + EMAs + 3 marker types: Setup Intel moments, bot buy entries, bot exit (TP/SL/TIMEOUT) |
| **🤖 Bot Positions** | Open paper trades with live Binance price, TP/SL progress bar, slot counter, recent closed trades |
| **📉 STERK Quality** | Closed paper trade analysis — cumulative PnL chart, daily breakdown, CSV export, plain-language summary |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Docker Compose (VPS — 4 CPU / 8GB RAM)       │
│                                                                  │
│  command_center  :4000  ←── Nginx SPA  (5 dashboard pages)      │
│  control_api     :8080  ←── FastAPI    (30+ endpoints, testbot) │
│  postgres        :5432  ←── PostgreSQL 16  (17 tables)          │
│  jojo_analytics  :8097  ←── SQL query service for indicators     │
│  indicator_engine:8099  ←── OHLCV import + TA + signal detect   │
│  openclaw_gateway       ←── Jojo1 AI   (Claude Sonnet 4.6)      │
│  tg_coordinator_bot     ←── Telegram 30-min market reports      │
│  tg_discuss_bot         ←── Kimi AI interactive chat bot        │
│  apex_engine            ←── Trading engine (signals, orders)    │
│  kimi_pattern_agent     ←── Nightly pattern analysis (03:00)    │
│  market_oracle_sandbox  ←── RSS + Yahoo Finance macro feed      │
└──────────────────────────────────────────────────────────────────┘
```

---

## P1 Setup Scoring System

The **setup judge** scores every `(coin × signal_type)` combination using all available history:

```
Score (0–100):
  Win rate   0–40 pts  ← % of trades profitable after 1h
  Avg PnL    0–30 pts  ← mean 1h return across all occurrences
  Sample size 0–15 pts ← min 10 trades required, bonus at n ≥ 100
  Regime     0–15 pts  ← bonus if signal performs better in current BTC regime

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

## Paper Trading Testbot

Runs as a background thread inside `control_api`. **No live trading — BloFin demo only.**

| Parameter | Value |
|-----------|-------|
| Entry condition | `STERK` verdict only |
| Stake per trade | $100 USD |
| Max concurrent trades | 3 |
| Take Profit | +4.5% |
| Stop Loss | −2.0% |
| Max duration | 2 hours (TIMEOUT) |
| Fee (round-trip) | 0.2% |
| Live price source | Binance public API |
| Storage | PostgreSQL `testbot_trades` |

Tracks price snapshots at 15m / 1h / 2h after entry for detailed outcome analysis.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.11, FastAPI, uvicorn |
| Database | PostgreSQL 16 (primary) + SQLite (legacy) |
| DB compat layer | `db/db_compat.py` — `?`→`%s`, `datetime()`→`NOW()` |
| Charts | TradingView Lightweight Charts v4.1.3 (open-source CDN) |
| Live prices | Binance public REST API (no key required) |
| Auth | Telegram OTP login + JWT-style session tokens |
| AI operator | Claude Sonnet 4.6 (Anthropic API) |
| Infrastructure | Docker Compose, Nginx, Cloudflare tunnel |
| Exchange | BloFin Demo (paper trading only) |

---

## Database Tables (PostgreSQL)

```sql
ohlcv_data           -- 4 years of 1h/4h candles (17 coins)
indicators_data      -- RSI, MACD hist, EMA21/55/200, ADX, BB, StochRSI per candle
historical_context   -- signal occurrences + future 1h/4h/24h PnL outcomes
crash_score_log      -- market crash probability score over time
testbot_trades       -- paper trade log (entry, exit, TP/SL/TIMEOUT, PnL, fees)
events               -- audit trail: bot OPEN/CLOSE events with full payload
signal_context       -- latest live signals from apex_engine
verdict_log          -- legacy signal verdict log
```

---

## Key API Endpoints

```http
# Live dashboard
GET  /live/signals                   current indicators + signal + P1 verdict per coin

# Setup intelligence
GET  /setup/scan                     P1 score all coins × signals in one bulk query
GET  /setup/chart-markers/{symbol}   STERK/TOESTAAN historical markers (chart overlay)

# Testbot
GET  /testbot/status                 bot running state + config + all-time stats
GET  /testbot/positions              open positions with live Binance price + current PnL
GET  /testbot/history?limit=100      closed trades with 15m/1h/2h/final PnL breakdown
GET  /testbot/markers/{symbol}       entry/exit timestamps for chart overlay
POST /testbot/start | /testbot/stop  start or stop the bot
POST /testbot/open                   manually open a test trade {symbol, signal, score}

# Chart
GET  /chart/markers/{symbol}         candles + EMAs + crash scores for chart
```

---

## Project Structure

```
.
├── control_api/
│   └── app/
│       ├── server.py            # FastAPI app — 30+ endpoints, auth, testbot integration
│       └── testbot.py           # Paper trading bot — background thread
├── dashboard/
│   ├── live_signals.html        # ⚡ Real-time signal overview
│   ├── setup_intelligence.html  # 📊 Historical setup quality
│   ├── chart.html               # 📈 Chart with 3 marker types
│   ├── bot_positions.html       # 🤖 Open paper positions
│   ├── sterk_quality.html       # 📉 Closed trade analysis
│   └── index.html               # Dashboard home + navigation
├── db/
│   ├── init.sql                 # PostgreSQL schema (17 tables + indices)
│   └── db_compat.py             # SQLite ↔ PostgreSQL compatibility layer
├── docs/
│   ├── SYSTEM_FULL.md           # Full system documentation
│   ├── P1_SETUP_JUDGE.md        # P1 scoring system
│   ├── P2_TESTBOT.md            # Paper trading testbot
│   └── P3_LIVE_DASHBOARD.md     # Live signals + chart markers
├── secrets/                     # *.env files — NEVER committed
├── docker-compose.yml
└── README.md
```

---

## Setup (development reference)

```bash
# 1. Clone
git clone https://github.com/frans1979valk/openclaw-apex-v2.git
cd openclaw-apex-v2

# 2. Create secrets
cp secrets/*.env.example secrets/*.env   # fill in API keys

# 3. Start
docker compose up -d

# 4. Open dashboard
# https://your-vps-ip:4000
```

**Required secrets:** `CONTROL_API_TOKEN`, `TG_BOT_TOKEN_COORDINATOR`, `TG_CHAT_ID`, `DATABASE_URL`

---

## Security

- Dashboard protected by **Telegram OTP** — login sends 6-digit code to your Telegram
- All API endpoints require `X-API-KEY` header
- Session tokens expire after 24 hours
- Secrets in `secrets/*.env` — gitignored, never pushed
- HTTPS via Cloudflare tunnel or self-signed certificate

---

## Current Status

| Feature | Status |
|---------|--------|
| P1 setup scoring engine | ✅ Live |
| Live signals dashboard | ✅ Live |
| Interactive charts + markers | ✅ Live |
| Paper trading testbot | ✅ Running (test phase) |
| Setup Intelligence page | ✅ Live |
| Cumulative PnL analysis | ✅ Live |
| Telegram trade alerts | 🔧 Planned |
| Short signals | 🔧 Planned |
| Real money trading | ⚙️ Supported — disabled by default (see below) |

---

## Live Trading (optional)

The platform is designed for **paper trading by default**, but live trading on BloFin is supported.

To enable live trading:

1. Set `ALLOW_LIVE=true` in `secrets/apex.env`
2. Replace the BloFin demo API keys with your **live account** API keys
3. Restart the engine: `docker compose restart apex_engine`

> **Warning:** Live trading uses real money. The platform is still in test phase. Use at your own risk. Start with small position sizes and monitor closely. The authors are not responsible for financial losses.

The AI operator (Jojo1) and all safety mechanisms (Gatekeeper, PARAM_BOUNDS, OTP confirmation) remain active in live mode.

---

## License

MIT — free to use, study and build upon. Not financial advice.

---

*Built with Claude Code + Anthropic API. AI operator Jojo1 runs on Claude Sonnet 4.6.*
