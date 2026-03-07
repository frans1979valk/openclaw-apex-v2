# Security — OpenClaw Apex Platform

## Network Isolation

### Open ports (externally reachable)

| Port | Service | Binding | Access |
|------|---------|---------|--------|
| 3000 | Dashboard (Nginx) | 0.0.0.0 | Public (HTML/JS only, no API) |
| 8080 | control_api | 0.0.0.0 | Public — secured with X-API-KEY header |

### Localhost-only ports (NOT public)

| Port | Service | Reason |
|------|---------|--------|
| 18789 | openclaw_gateway | Operator OS — internal only, Telegram is the only UI |
| 8090 | openclaw_runtime | Agent orchestrator — internal |

**Rule:** If you set up a reverse proxy (Nginx/Caddy), NEVER expose 18789 publicly without auth. The gateway has its own token (`OPENCLAW_GATEWAY_TOKEN`) but use a reverse proxy with additional authentication if you want to reach it from the internet.

### Docker networks

| Network | Services | Description |
|---------|----------|-------------|
| `trade_net` | apex_engine, control_api | Trading internal network |
| `agent_net` | control_api, openclaw*, dashboard, telegram bots | Agent communication |

`apex_engine` is NOT on `agent_net` — OpenClaw can only reach the engine via `control_api`.

---

## Secrets Management

### Location

All secrets are stored in `secrets/*.env`. This directory is gitignored.

```
secrets/
├── apex.env                    ← BloFin keys + trading config
├── control_api.env             ← API token + Telegram config
├── openclaw.env                ← Kimi/Anthropic keys for learning agent
├── openclaw_gateway.env        ← Gateway token + Anthropic + Telegram
├── telegram_coordinator.env    ← Coordinator bot token
└── telegram_discuss.env        ← Discuss bot token
```

**Never commit.** Verify with:
```bash
git status  # secrets/*.env must NEVER appear
cat .gitignore | grep secrets
```

### .env.example templates

The `*.env.example` files ARE in git (no real values, structure only).

---

## Gateway Token

The `OPENCLAW_GATEWAY_TOKEN` protects the WebSocket/HTTP API of the gateway.

**Generate a new token:**
```bash
openssl rand -hex 32
```

**Rotate the token:**
1. Generate new token
2. Update `secrets/openclaw_gateway.env`
3. `docker compose restart openclaw_gateway`

---

## Telegram Allowlist

OpenClaw is configured with `dmPolicy: "allowlist"` — only your User ID can control the bot.

```json
"dmPolicy": "allowlist",
"allowedIds": ["${TG_ALLOWED_USER_ID}"]
```

**Add someone:** Update `TG_ALLOWED_USER_ID` in `secrets/openclaw_gateway.env` (multiple IDs: comma-separated) and restart the gateway.

**Verify:** Other Telegram accounts CANNOT use the bot.

---

## What OpenClaw May NEVER Do

These restrictions are hardcoded in the gatekeeper skill and the control_api:

| Prohibition | Enforcement |
|-------------|-------------|
| Call exchange API | Gatekeeper skill explicitly forbids it; tool scripts only talk to control_api |
| Use BloFin keys | OpenClaw container NEVER has these keys in its env |
| Set `ALLOW_LIVE=true` | Hardcoded `false` in apex.env; no tool script touches this variable |
| Parameters outside PARAM_BOUNDS | `tool_propose_params.py` auto-clamps + errors on violation |
| > 3 apply actions per day | Enforced by `MAX_APPLIES_PER_DAY=3` in control_api |
| Apply without confirmation | control_api `CONFIRM_REQUIRED=true` blocks unconfirmed applies |

---

## PARAM_BOUNDS (hardcoded safety limits)

Defined in `openclaw_tools/registry.json` and enforced in `tool_propose_params.py`:

| Parameter | Min | Max |
|-----------|-----|-----|
| `rsi_buy_threshold` | 20 | 40 |
| `rsi_sell_threshold` | 60 | 80 |
| `stoploss_pct` | 1.5 | 6.0 |
| `takeprofit_pct` | 3.0 | 12.0 |
| `position_size_base` | 1 | 5 |

Changing requires code modification in `tool_propose_params.py` — not via env vars.

---

## Confirm Policy

Two modes in control_api:

| Mode | Behavior |
|------|----------|
| `CONFIRM_REQUIRED=true` (default) | Every `apply` blocks until `/ok <id>` is sent via Telegram |
| `CONFIRM_REQUIRED=false` | Agent can auto-apply (only for automated test environments) |

**Flash-crash exception:** `tool_pause_trading` and `tool_resume_trading` are always immediate — they require no confirmation. Applying parameters is always confirm-required.

---

## API Key Overview

| Service | Key type | Location | Has trading permission? |
|---------|----------|----------|------------------------|
| apex_engine | BloFin API key/secret/passphrase | secrets/apex.env | Yes (demo only) |
| control_api | CONTROL_API_TOKEN (internal) | secrets/control_api.env | Gatekeeper |
| openclaw_gateway | ANTHROPIC_API_KEY (Sonnet) | secrets/openclaw_gateway.env | No |
| openclaw_gateway | OPENCLAW_GATEWAY_TOKEN | secrets/openclaw_gateway.env | No |
| openclaw (learning agent) | KIMI_API_KEY, ANTHROPIC_API_KEY | secrets/openclaw.env | No |

**OpenClaw gateway NEVER has BloFin keys.**

---

## Version Pinning & Supply Chain

- **OpenClaw submodule pinned to v2026.3.2** (includes ClawJacked fix from v2026.2.25)
- Dockerfile.gateway checks minimum version at build time: `< 2026.2.25` → hard fail
- **No marketplace skills:** `skills.allowBundled` limited to `["browser", "github"]`
- All custom skills come from `./skills/` (vendored in our repo)
- Skills mounted read-only in the container (`./skills:/workspace/skills:ro`)
- Update procedure: `git submodule update --remote`, check tag, rebuild

---

## Audit & Logging

All tool calls are logged in `/var/apex/openclaw_tools.log` (mounted volume `apex_data`).

View live:
```bash
docker compose exec control_api tail -f /var/apex/openclaw_tools.log
```

View gateway logs:
```bash
docker compose logs -f openclaw_gateway
```

---

## Go-Live Checklist

- [ ] `secrets/openclaw_gateway.env` created with real values
- [ ] `OPENCLAW_GATEWAY_TOKEN` generated with `openssl rand -hex 32`
- [ ] New Telegram bot created via @BotFather
- [ ] `TG_ALLOWED_USER_ID` set to your own ID
- [ ] Port 18789 is NOT publicly reachable (check: `ss -tlnp | grep 18789` → must show `127.0.0.1`)
- [ ] `ALLOW_LIVE=false` in `secrets/apex.env` (confirm when switching to live)
- [ ] secrets/ is in `.gitignore` and has not been pushed
