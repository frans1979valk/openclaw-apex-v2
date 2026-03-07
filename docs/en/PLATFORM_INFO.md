# OpenClaw Apex Trading Platform — Full Documentation

**Version:** 2.0 (2026-03-07)
**Status:** Live on VPS, demo trading mode (BloFin paper account)

---

## 1. What is this system?

A fully autonomous AI crypto trading platform consisting of 16 Docker containers. The platform **runs fully automatically — without manual intervention**. It:
- Automatically selects the best coins via AI (Kimi)
- Analyzes market data with technical indicators (4 years of historical data)
- Places virtual trades (demo mode — no real money)
- Learns from its own trades and optimizes parameters
- Monitors the market via Telegram bots
- Sends alerts and reports to Telegram

**Owner:** Platform operator
**AI Operator:** Jojo1 (runs in `openclaw_gateway` container, Claude Sonnet 4.6)
**Platform language:** Python (services), TypeScript (gateway)

---

## 1b. OpenClaw — The Master Framework (Backbone)

**OpenClaw is the heart of the platform.** It is a TypeScript-based agent runtime framework that makes the platform operate fully autonomously.

### What OpenClaw does

OpenClaw runs as the `openclaw_gateway` container and is the only component that coordinates all other services:

| Function | Description |
|----------|-------------|
| **AI engine** | Claude Sonnet 4.6 as language model — understands market data, makes decisions |
| **Tool system** | Calls Python scripts: indicator_engine, control_api, sniper, market data |
| **Skill system** | Complex workflows (analysis, report, strategy) as reusable skills |
| **Multi-agent** | Controls sub-agents: Research Agent, Risk Agent for deeper analyses |
| **Telegram** | Primary communication channel — receives questions, sends alerts and reports |
| **Persistent memory** | Remembers context, decisions and learning effects across sessions |
| **Collab system** | Inbox-based communication with Dev (Claude Code) for updates |

### Autonomous operation

The platform runs 24/7 fully autonomously:

```
[apex_engine] — Every 10s: analyzes 40 coins, places demo orders
     ↑
[indicator_engine] — Provides TA data (RSI, MACD, EMA, Sniper monitoring)
     ↑
[tg_coordinator_bot] — Every 30min: market report to Telegram
     ↑
[kimi_pattern_agent] — Every night 03:00: pattern analysis on historical data
     ↑
[openclaw_gateway / Jojo1] — Coordinates everything, responds to events
```

### Jojo1 as autonomous operator

Jojo1 is **not a chatbot** — it is an autonomous operator that independently:
1. Requests and interprets market data
2. Adjusts configurations via the proposals system
3. Sets snipers at favorable conditions
4. Pauses trading when danger signals appear
5. Informs the owner via Telegram when action is relevant

The owner only needs to intervene when they **want to** — the system decides autonomously.

### OpenClaw vs. other services

```
OpenClaw (master/brain)
    ├── apex_engine        → executes trades (slave of config)
    ├── indicator_engine   → provides data (slave of queries)
    ├── control_api        → manages config (slave of proposals)
    ├── tg_discuss_bot     → Kimi market chat (independent)
    └── all other svcs     → supporting roles
```

**OpenClaw is the only component that thinks. The rest executes.**

---

## 2. Container Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         agent_net (internal)                        │
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
│  │  command_center  │      │  market_oracle  │                     │
│  │  :4000 Web UI    │      │  :8095 sandbox  │                     │
│  └──────────────────┘      └─────────────────┘                     │
│                                                                     │
│  ┌──────────────────┐      ┌─────────────────┐                     │
│  │ tg_coordinator   │      │ tg_discuss_bot  │                     │
│  │ 30min reports    │      │ Kimi AI chat    │                     │
│  └──────────────────┘      └─────────────────┘                     │
│                                                                     │
│  ┌──────────────────┐      ┌─────────────────┐                     │
│  │ kimi_pattern     │      │  jojo_analytics  │                    │
│  │ agent :8098      │      │  :8097 TA queries│                    │
│  └──────────────────┘      └─────────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Services Overview

| Service | Port | Network | Function |
|---------|------|---------|----------|
| `openclaw_gateway` | 127.0.0.1:18789 | agent_net | Jojo1 — Claude Sonnet 4.6, Telegram AI operator |
| `control_api` | 0.0.0.0:8080 | trade_net + agent_net | Gatekeeper API, policy engine, authentication, SSE stream |
| `apex_engine` | — (internal) | trade_net | Trading engine: signals, orders, crash detection |
| `command_center` | 127.0.0.1:4000 | agent_net | Web UI — 5 dashboard pages (Nginx SPA) |
| `indicator_engine` | 127.0.0.1:8099 | trade_net | Historical OHLCV import + TA + signal detection |
| `jojo_analytics` | 127.0.0.1:8097 | agent_net | TA indicators + DB query service |
| `market_oracle_sandbox` | 127.0.0.1:8095 | agent_net | Isolated macro analysis (RSS + Yahoo Finance) |
| `tg_coordinator_bot` | — (internal) | agent_net | Telegram: automatic 30-min market reports |
| `tg_discuss_bot` | — (internal) | agent_net | Telegram: interactive bot (Kimi AI) |
| `kimi_pattern_agent` | 127.0.0.1:8098 | agent_net | Nightly pattern analysis (03:00) |
| `postgres` | 5432 | both | PostgreSQL 16, database: apex |

---

## 4. Dashboard Pages

| Page | URL | Description |
|------|-----|-------------|
| **Home** | `/` | Navigation + platform status overview |
| **Live Signals** | `/live_signals.html` | Real-time RSI/MACD/ADX per coin, active signal, P1 verdict |
| **Setup Intelligence** | `/setup_intelligence.html` | Historical quality per (coin x signal type) |
| **Chart** | `/chart.html` | Candlestick chart + 3 marker types |
| **Bot Positions** | `/bot_positions.html` | Open paper positions with live price + TP/SL progress |
| **STERK Quality** | `/sterk_quality.html` | Closed trades analysis, cumulative PnL chart |

---

## 5. P1 Setup Scoring System

The **setup judge** scores every `(coin × signal_type)` combination using all available history:

```
Score (0–100):
  Win rate     0–40 pts  ← % of trades profitable after 1h
  Avg PnL      0–30 pts  ← mean 1h return across all occurrences
  Sample size  0–15 pts  ← min 10 trades required, bonus at n >= 100
  Regime       0–15 pts  ← bonus if signal performs better in current BTC regime

Verdict thresholds:
  STERK         score >= 70  AND  win% >= 55%  AND  avg_pnl >= 0.20%  AND  n >= 20
  TOESTAAN      score >= 50
  TOESTAAN_ZWAK score >= 30
  SKIP          below thresholds or negative edge
```

Example output (DOGE / BREAKOUT_BULL):
```
score=78  win%=83.3  avg_1h=+0.785%  n=30 → STERK
```

---

## 6. Signal Types

| Signal | Trigger conditions |
|--------|-------------------|
| `BREAKOUT_BULL` | Price > upper Bollinger Band + RSI > 50 + volume > 1.5× avg |
| `MOMENTUM` | EMA21 > EMA55 > EMA200 + RSI 50–65 + MACD bullish + ADX > 25 |
| `BUY` | RSI < 32 + MACD turning up, or StochRSI oversold (k < 20, k > d) |

---

## 7. Paper Trading Testbot

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

---

## 8. Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.11, FastAPI, uvicorn |
| Database | PostgreSQL 16 (primary) + SQLite (legacy) |
| DB compat layer | `db/db_compat.py` — `?`→`%s`, `datetime()`→`NOW()` |
| Charts | TradingView Lightweight Charts v4.1.3 |
| Live prices | Binance public REST API (no key required) |
| Auth | Telegram OTP login + JWT-style session tokens |
| AI operator | Claude Sonnet 4.6 (Anthropic API) |
| Infrastructure | Docker Compose, Nginx, Cloudflare tunnel |
| Exchange | BloFin Demo (paper trading only) |

---

## 9. Security Model

- Dashboard protected by **Telegram OTP** — login sends 6-digit code to Telegram
- All API endpoints require `X-API-KEY` header
- Session tokens expire after 24 hours
- OpenClaw NEVER has exchange (BloFin) keys
- ALLOW_LIVE is hardcoded `false` — cannot be changed via proposals
- All parameter changes require OTP confirmation from owner
- Secrets in `secrets/*.env` — gitignored, never pushed
