# OpenClaw Apex — English Documentation

This folder contains English translations of all platform documentation.
The original Dutch versions are in the parent `docs/` folder.

---

## Documents

| File | Contents |
|------|----------|
| [PLATFORM_INFO.md](PLATFORM_INFO.md) | Platform overview — what it is, all containers, architecture |
| [DATA_ARCHITECTURE.md](DATA_ARCHITECTURE.md) | Database schema, data pipeline, indicator definitions, P1 scoring |
| [P3_LIVE_DASHBOARD.md](P3_LIVE_DASHBOARD.md) | Live signals page, chart markers (3 types), signal detection logic |
| [GATEKEEPER_API.md](GATEKEEPER_API.md) | Control API endpoints — proposals, policy, confirm flow |
| [INDICATOR_ENGINE.md](INDICATOR_ENGINE.md) | TA engine — OHLCV import, indicators, pattern matching, signal filter |
| [MARKET_ORACLE.md](MARKET_ORACLE.md) | Macro analysis sandbox — RSS feeds, Yahoo Finance, event analysis |
| [COMMAND_CENTER.md](COMMAND_CENTER.md) | Web UI — authentication, endpoints, audit logging |
| [OPENCLAW_OPERATOR_OS.md](OPENCLAW_OPERATOR_OS.md) | Jojo1 AI operator — setup, daily usage, confirm flow, troubleshooting |
| [SECURITY.md](SECURITY.md) | Network isolation, secrets management, what OpenClaw may never do |

---

## Quick Start

1. Read [PLATFORM_INFO.md](PLATFORM_INFO.md) for the full system overview
2. Read [SECURITY.md](SECURITY.md) before deploying
3. Follow [OPENCLAW_OPERATOR_OS.md](OPENCLAW_OPERATOR_OS.md) to set up Jojo1
4. Use [GATEKEEPER_API.md](GATEKEEPER_API.md) for API integration

---

## Key Concepts

- **P1 Setup Scoring** — rates every (coin × signal) combo as STERK/TOESTAAN/TOESTAAN_ZWAK/SKIP based on 4 years of history
- **Testbot** — paper trading bot that only trades STERK setups ($100 stake, TP 4.5%, SL 2.0%)
- **OpenClaw / Jojo1** — Claude Sonnet 4.6 AI that operates the platform autonomously via Telegram
- **Gatekeeper** — policy engine that validates all AI proposals before they are applied
