# OpenClaw Operator-OS — Guide

## What is this?

OpenClaw Gateway is the "Operator OS" layer of the Apex platform. It is the [openclaw/openclaw](https://github.com/openclaw/openclaw) TypeScript framework running as a Telegram-driven AI assistant on top of the trading stack.

```
Owner (Telegram DM) → OpenClaw Gateway (port 18789, localhost)
                              ↓
                   Gatekeeper Skill (Python tools)
                              ↓ HTTP
                      control_api (:8080)
                              ↓
                     apex_engine (BloFin demo)
```

**OpenClaw never has:** exchange keys, direct trade access, or ALLOW_LIVE=true.

---

## One-time Setup

### Step 1: Create a new Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Name: `OpenClaw Operator` (or your choice)
4. Username: `openclaw_operator_bot` (or your choice, must end with `_bot`)
5. Copy the token you receive (format: `123456:ABCDEF...`)

### Step 2: Find your Telegram User ID

1. Open Telegram and search for **@userinfobot** or **@getidsbot**
2. Send `/start`
3. Note your **User ID** (number, e.g. `7381250590`)

### Step 3: Create the secrets file

```bash
cp secrets/openclaw_gateway.env.example secrets/openclaw_gateway.env
```

Fill in:
```
OPENCLAW_GATEWAY_TOKEN=<generate with: openssl rand -hex 32>
ANTHROPIC_API_KEY=<your Anthropic key>
TELEGRAM_BOT_TOKEN=<token from step 1>
TG_ALLOWED_USER_ID=<your User ID from step 2>
CONTROL_API_URL=http://control_api:8080
CONTROL_API_TOKEN=changeme-strong-token
```

### Step 4: Build and start

```bash
# Build the gateway (takes 3-8 minutes on first run)
docker compose build openclaw_gateway

# Start everything
docker compose up -d

# Check if gateway is running
curl http://127.0.0.1:18789/health
```

### Step 5: Telegram pairing

1. Send a DM to your new bot in Telegram
2. The bot sends a pairing request
3. Accept — after that you can control everything

---

## Day-to-day Usage

### Get status

Send to the bot:
```
status
```
Or:
```
what is the current market?
```

OpenClaw calls `tool_status` and responds with current signals, crash_score and win_rate.

### Run backtest

```
backtest XRP-USDT
```
Or specific:
```
backtest XRP-USDT 4h
```

### Submit parameter proposal

Ask the agent for analysis:
```
analyze the win_rate and suggest better parameters if needed
```

The agent:
1. Calls `tool_status`
2. Runs a backtest
3. Submits a proposal if profit_factor > 1.15
4. Sends you: "Confirm with /ok `<proposal_id>`"

### Confirm proposal

```
/ok abc123
```

This counts as your "YES" — the agent applies the parameters.

### Emergency stop

```
stop
```
Or:
```
pause trading for 60 minutes, too much volatility
```

### Resume trading

```
resume trading
```

---

## Switching Agents

OpenClaw has 3 specialized agents. The **operator_risk_agent** is active by default via Telegram.

To switch:
```
switch to research agent
```
```
switch to builder agent
```
```
switch back to risk
```

### Agent permissions

| Agent | Can read | Can write | Can execute |
|-------|----------|-----------|-------------|
| `operator_risk_agent` (default) | status, news, backtest | propose_params | pause, resume (+ apply after YES) |
| `research_agent` | status, news, backtest, browser | — | — |
| `builder_agent` | status, news, backtest, git | propose_params, git commits | — (never deploy without proposal) |

---

## Confirm Flow

### Normal

```
You: "suggest better stoploss"
Agent: analyzes → backtest → proposal_id: abc123
       "Confirm with /ok abc123"
You: "/ok abc123"
Agent: executes apply → "Parameters updated"
```

### Flash-Crash (automatic)

The agent actively scans for dangerous conditions and **pauses automatically** (without your confirmation) when:

| Condition | Action | Duration |
|-----------|--------|----------|
| crash_score > 70 | Auto-pause | 30 min |
| crash_score > 85 | Auto-pause | 60 min |
| win_rate < 40% (> 20 trades) | Auto-pause | 60 min |
| 2+ BTC_CASCADE events (1 hour) | Auto-pause | 45 min |
| FLASH_CRASH event | Auto-pause | 20 min |

After an auto-pause, the agent always sends a notification: reason + duration.

### What is NEVER automatic

- `tool_apply_proposal` (apply parameters) — always requires YES
- `ALLOW_LIVE=true` — forbidden in code
- Direct exchange call — forbidden in code

---

## Checking Gateway Status

From the VPS (shell):
```bash
# Health endpoint
curl http://127.0.0.1:18789/health

# Container logs
docker compose logs -f openclaw_gateway

# Skills list in container
docker compose exec openclaw_gateway node openclaw.mjs skills list

# Gateway status
docker compose exec openclaw_gateway node openclaw.mjs gateway status
```

---

## File Overview

```
openclaw_config/
└── openclaw.json          ← main configuration (mounted read-only)

skills/
└── gatekeeper/
    └── SKILL.md           ← custom Gatekeeper skill

openclaw_tools/
└── scripts/               ← Python tool scripts (mounted as /workspace/tools/)
    ├── tool_status.py
    ├── tool_run_backtest.py
    ├── tool_propose_params.py
    ├── tool_apply_proposal.py
    ├── tool_pause_trading.py
    ├── tool_resume_trading.py
    └── tool_fetch_news.py

secrets/
├── openclaw_gateway.env.example   ← template
└── openclaw_gateway.env           ← real keys (NEVER in git)

Dockerfile.gateway                 ← builds openclaw/openclaw TypeScript
```

---

## Troubleshooting

**Bot not responding:**
```bash
docker compose logs openclaw_gateway | tail -50
```
Check: correct bot token? TG_ALLOWED_USER_ID correct? Container running?

**"Unauthorized" on control_api calls:**
Check `CONTROL_API_TOKEN` in `secrets/openclaw_gateway.env` — must match `secrets/control_api.env`.

**Build failed (pnpm errors):**
```bash
docker compose build --no-cache openclaw_gateway
```
Or check Node.js version in the container (requires 22.12.0+).

**Skills not found:**

1. Verify that `./skills/gatekeeper/SKILL.md` exists on the host:
```bash
cat skills/gatekeeper/SKILL.md | head -5
```

2. Verify that the volume is correctly mounted in the container:
```bash
docker compose exec openclaw_gateway ls -la /workspace/skills/gatekeeper/
```

3. Check `extraDirs` in config:
```bash
docker compose exec openclaw_gateway cat /root/.openclaw/openclaw.json | grep -A3 extraDirs
```

4. Full restart required after skill addition (config reload is not enough):
```bash
docker compose restart openclaw_gateway
```

5. Fallback: if `extraDirs` doesn't work, copy skills to `~/.openclaw/skills/` in the container:
```bash
docker compose exec openclaw_gateway cp -r /workspace/skills/* /root/.openclaw/skills/ 2>/dev/null
docker compose restart openclaw_gateway
```

**Health endpoint returns HTML instead of JSON:**
Known bug in some OpenClaw versions. Check with:
```bash
curl -s http://127.0.0.1:18789/health | head -1
```
If you see `<html`: the gateway control UI is overriding `/health`. Use instead:
```bash
docker compose exec openclaw_gateway node openclaw.mjs gateway status
```
