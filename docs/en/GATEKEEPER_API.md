# Gatekeeper API — Reference

## Overview

The Gatekeeper is the policy engine inside `control_api`. The OpenClaw Operator submits proposals through this API. Every action is validated against PARAM_BOUNDS, daily limits, and requires Telegram OTP confirmation (except flash-crash actions).

## Authentication

All endpoints require the `X-API-KEY` header:
```
X-API-KEY: <CONTROL_API_TOKEN>
```

---

## Endpoints

### GET /status

Full platform status.

```bash
curl -s http://127.0.0.1:8080/status -H "X-API-KEY: $TOKEN" | python3 -m json.tool
```

**Response:**
```json
{
  "mode": "demo",
  "allow_live": false,
  "trading": { "halted": false, "paused_until": null, "reason": "" },
  "last_signals": { "BTC-USDT": "HOLD", "ETH-USDT": "BUY" },
  "open_positions": [],
  "crash_max_24h": 45,
  "overall_win_rate": 62.5,
  "risk_flags": [],
  "macro_context": {},
  "applies_today": 1,
  "max_applies_per_day": 3
}
```

---

### POST /proposals

Submit a proposal.

```bash
curl -s -X POST http://127.0.0.1:8080/proposals \
  -H "X-API-KEY: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "PARAM_CHANGE",
    "payload": { "rsi_buy_threshold": 32, "stoploss_pct": 3.0 },
    "reason": "Win rate too low, more conservative RSI",
    "requested_by": "openclaw_operator",
    "requires_confirm": true
  }'
```

**Proposal types:**

| Type | Description | Auto-apply on flash-crash? |
|------|-------------|---------------------------|
| `PAUSE` | Pause trading | Yes (without confirm) |
| `RESUME` | Resume trading | No |
| `PARAM_CHANGE` | Change trading parameters | No |
| `COIN_ALLOW` | Add coin to allowlist | No |
| `RUN_BACKTEST` | Request backtest | No |
| `DEPLOY_STAGING` | Deploy to staging | No |
| `NO_BUY` | Sell only, no new buys | Yes (without confirm) |
| `EXIT_ONLY` | Exit positions only | Yes (without confirm) |

**Response:**
```json
{
  "ok": true,
  "proposal_id": "a1b2c3d4",
  "type": "PARAM_CHANGE",
  "status": "pending",
  "requires_confirm": true,
  "message": "Waiting for Telegram confirmation (OTP)"
}
```

On flash-crash auto-apply:
```json
{
  "ok": true,
  "proposal_id": "e5f6g7h8",
  "type": "PAUSE",
  "status": "auto_applied",
  "requires_confirm": false,
  "message": "Flash-crash action PAUSE automatically executed"
}
```

---

### GET /proposals/v2?state=pending

List proposals with status filter.

```bash
# All proposals
curl -s "http://127.0.0.1:8080/proposals/v2" -H "X-API-KEY: $TOKEN"

# Pending only
curl -s "http://127.0.0.1:8080/proposals/v2?state=pending" -H "X-API-KEY: $TOKEN"
```

---

### POST /proposals/{id}/confirm

Confirm a proposal with OTP (sent via Telegram).

```bash
curl -s -X POST http://127.0.0.1:8080/proposals/a1b2c3d4/confirm \
  -H "X-API-KEY: $TOKEN" \
  -H "X-OTP: 123456"
```

**Response:**
```json
{
  "ok": true,
  "proposal_id": "a1b2c3d4",
  "status": "confirmed",
  "applied": true,
  "applies_today": 2
}
```

**Possible errors:**
- `403`: Invalid OTP
- `404`: Proposal not found
- `429`: Max applies per day reached
- `400`: PARAM_BOUNDS violation / proposal no longer pending

---

### GET /policy

Show Gatekeeper policy rules.

```bash
curl -s http://127.0.0.1:8080/policy -H "X-API-KEY: $TOKEN"
```

**Response:**
```json
{
  "param_bounds": {
    "rsi_buy_threshold": { "min": 20, "max": 40 },
    "rsi_sell_threshold": { "min": 60, "max": 80 },
    "stoploss_pct": { "min": 1.5, "max": 6.0 },
    "takeprofit_pct": { "min": 3.0, "max": 12.0 },
    "position_size_base": { "min": 1, "max": 5 }
  },
  "max_applies_per_day": 3,
  "flashcrash_auto_actions": ["PAUSE", "NO_BUY", "EXIT_ONLY"],
  "allowed_proposal_types": ["PAUSE", "RESUME", "PARAM_CHANGE", "COIN_ALLOW", "RUN_BACKTEST", "DEPLOY_STAGING"],
  "allow_live": false,
  "confirm_required": true
}
```

---

### POST /context/macro

Update macro-economic context (from Market Oracle).

```bash
curl -s -X POST http://127.0.0.1:8080/context/macro \
  -H "X-API-KEY: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis": { "short_term": { "outlook": "bearish", "confidence": 0.7 } },
    "key_factors": ["Fed rate hike"],
    "suggested_actions": ["PAUSE"],
    "timestamp": "2026-03-05T20:00:00Z"
  }'
```

### GET /context/macro

Get current macro context.

```bash
curl -s http://127.0.0.1:8080/context/macro -H "X-API-KEY: $TOKEN"
```

---

## Policy Rules

### PARAM_BOUNDS

| Parameter | Min | Max |
|-----------|-----|-----|
| `rsi_buy_threshold` | 20 | 40 |
| `rsi_sell_threshold` | 60 | 80 |
| `stoploss_pct` | 1.5% | 6.0% |
| `takeprofit_pct` | 3.0% | 12.0% |
| `position_size_base` | 1 | 5 |

Values outside bounds are automatically clamped + violation reported.

### Daily limit

Max **3 applies per day** (UTC). Counter resets at midnight.

### Flash-crash auto-apply

`PAUSE`, `NO_BUY`, and `EXIT_ONLY` may be applied without confirmation when `requires_confirm: false` is provided. All other types always require OTP.

### ALLOW_LIVE

May **NEVER** be enabled via a proposal. Hard-rejected with HTTP 403.

---

## Confirm Flow

```
OpenClaw → POST /proposals { type, payload, reason }
           ← { proposal_id, status: "pending" }
           → Telegram: "PROPOSAL a1b2c3d4 — OTP: 123456"

Owner → reads Telegram, copies OTP

OpenClaw → POST /proposals/a1b2c3d4/confirm  (X-OTP: 123456)
           ← { ok, applied: true }
           → action executed (pause/param change/etc)
```
