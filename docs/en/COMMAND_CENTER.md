# Jojo1 Command Center

Secure web interface for the AI operator (Jojo1) and the platform owner.

## Architecture

```
Browser (:4000)  →  Command Center (FastAPI)  →  control_api (:8080)
                                               →  market_oracle_sandbox (:8095)
```

The Command Center is a **proxy** with its own authentication, audit logging and rate limiting. All trading actions go through control_api — the Command Center itself executes no trades.

## Port & Access

| Port | Binding | Access |
|------|---------|--------|
| 4000 | 127.0.0.1 | Localhost only (reverse proxy needed for external access) |

## Authentication

### Login flow
1. `POST /cc/auth/request` — enter email
2. 6-digit OTP sent via Telegram
3. `POST /cc/auth/verify` — enter code
4. Session token (64 hex chars), **8 hours valid**
5. Send token as `Authorization: Bearer <token>` header

### Rate limiting
Max 5 login attempts per 10 minutes per IP address. After that, HTTP 429.

### Session storage
SQLite database at `/var/command_center/cc.db`. Table `sessions` with token, email, expiry.

## Endpoints

### Auth

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/cc/auth/request` | None | Request OTP (email in body) |
| POST | `/cc/auth/verify` | None | Verify OTP, receive session token |
| POST | `/cc/auth/logout` | Bearer | End session |

### Status & Data

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/cc/status` | Bearer | Platform status (proxy to `/status`) |
| GET | `/cc/balance` | Bearer | Demo account balance and P&L |
| GET | `/cc/oracle` | Bearer | Market Oracle scan (proxy to `/scan`) |

### Proposals

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/cc/proposals?state=pending` | Bearer | List pending proposals |
| POST | `/cc/proposals/{id}/confirm` | Bearer + X-OTP | Confirm proposal with OTP |
| POST | `/cc/proposals/{id}/reject` | Bearer | Reject proposal |

### Trading Controls

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/cc/pause` | Bearer | Pause trading (`{"minutes": 30, "reason": "..."}`) |
| POST | `/cc/resume` | Bearer | Resume trading |

### Backtest

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/cc/backtest/{symbol}?interval=1h&months=3` | Bearer | Historical backtest |

### Logs

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/cc/logs?level=ERROR&limit=100` | Bearer | Audit logs (filterable) |

### Health

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/cc/health` | None | `{"status": "ok"}` |

## Frontend

Two pages, dark theme, mobile-friendly, vanilla JS:

- `/` — Login page (email + OTP)
- `/dashboard` — Main dashboard with 7 sections:

| Section | Content | Auto-refresh |
|---------|---------|-------------|
| Status | Engine state, crash_score, win_rate, active coins | 15s |
| Account | Balance, P&L, recent orders | 60s |
| Proposals | List + confirm/reject buttons + OTP input | 15s |
| Backtest | Symbol + interval selection, results per signal type | Manual |
| Oracle | Market scan button, JSON result | Manual |
| Logs | Filterable by level, max 500 lines | 30s |
| Controls | Pause/Resume buttons | — |

## Audit Logging

All actions are logged in `/var/command_center/audit.log`:

```
2026-03-05 21:00:00 | user=owner@email.com | ip=10.0.0.1 | action=confirm_proposal | result=confirmed | proposal=a1b2c3d4
2026-03-05 21:01:00 | user=owner@email.com | ip=10.0.0.1 | action=pause_trading | result=ok | minutes=30 reason=Test
2026-03-05 21:02:00 | user=test@bad.com | ip=10.0.0.2 | action=login_request | result=denied | email not allowed
```

Logged actions: `login_request`, `login_verify`, `view_status`, `view_proposals`, `confirm_proposal`, `reject_proposal`, `pause_trading`, `resume_trading`, `run_backtest`, `oracle_scan`.

## Security

- **Security headers:** CSP, X-Frame-Options: DENY, X-XSS-Protection, nosniff, strict referrer
- **CORS:** Own domain only (no cross-origin)
- **ALLOW_LIVE:** Not present as toggle — read-only display only
- **Email whitelist:** `ALLOWED_EMAIL` env var limits who can log in
- **Rate limiting:** 5 attempts per 10 min per IP
- **Sessions:** SQLite, 8 hour TTL, explicitly removed on logout
- **Audit trail:** Every request logged with user, IP, action, result

## Docker

```yaml
command_center:
  build: ./command_center
  env_file:
    - ./secrets/command_center.env
  volumes:
    - cc_data:/var/command_center
  networks:
    - agent_net
  ports:
    - "127.0.0.1:4000:4000"
  depends_on:
    - control_api
  restart: unless-stopped
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CONTROL_API_URL` | Yes | `http://control_api:8080` |
| `CONTROL_API_TOKEN` | Yes | Shared token with control_api |
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token for OTP delivery |
| `TG_CHAT_ID` | Yes | Telegram chat ID for OTP |
| `ALLOWED_EMAIL` | No | Email whitelist (empty = all emails) |
| `SESSION_SECRET` | Yes | Random hex string for session signing |
| `ORACLE_URL` | Yes | `http://market_oracle_sandbox:8095` |

## Testing

```bash
# Build and start
docker compose build command_center
docker compose up -d command_center

# Health check
curl -s http://127.0.0.1:4000/cc/health | python3 -m json.tool

# Login flow
curl -s -X POST http://127.0.0.1:4000/cc/auth/request \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
# → Receive OTP via Telegram

curl -s -X POST http://127.0.0.1:4000/cc/auth/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "code": "123456"}'
# → {"ok": true, "token": "abc123...", "expires_at": "..."}

# Get status
curl -s http://127.0.0.1:4000/cc/status \
  -H "Authorization: Bearer <token>"

# Confirm proposal
curl -s -X POST http://127.0.0.1:4000/cc/proposals/a1b2c3d4/confirm \
  -H "Authorization: Bearer <token>" \
  -H "X-OTP: 123456"
```

## Reverse Proxy (optional)

For external access via HTTPS, add a Caddy or Nginx reverse proxy:

```
# Caddyfile example
commandcenter.yourdomain.com {
    reverse_proxy 127.0.0.1:4000
}
```
