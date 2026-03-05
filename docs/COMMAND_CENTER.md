# Jojo1 Command Center

Beveiligde webinterface voor de AI operator (Jojo1) en eigenaar (Frans).

## Architectuur

```
Browser (:4000)  →  Command Center (FastAPI)  →  control_api (:8080)
                                               →  market_oracle_sandbox (:8095)
```

Command Center is een **proxy** met eigen authenticatie, audit logging en rate limiting. Alle trading acties lopen via control_api — het Command Center voert zelf geen trades uit.

## Poort & Toegang

| Poort | Binding | Toegang |
|-------|---------|---------|
| 4000 | 127.0.0.1 | Alleen localhost (reverse proxy nodig voor extern) |

## Authenticatie

### Login flow
1. `POST /cc/auth/request` — email invoeren
2. 6-cijferige OTP wordt via Telegram gestuurd
3. `POST /cc/auth/verify` — code invoeren
4. Session token (64 hex chars), **8 uur geldig**
5. Token meesturen als `Authorization: Bearer <token>` header

### Rate limiting
Max 5 loginpogingen per 10 minuten per IP-adres. Daarna HTTP 429.

### Sessie opslag
SQLite database in `/var/command_center/cc.db`. Tabel `sessions` met token, email, expiry.

## Endpoints

### Auth

| Method | URL | Auth | Beschrijving |
|--------|-----|------|-------------|
| POST | `/cc/auth/request` | Geen | OTP aanvragen (email in body) |
| POST | `/cc/auth/verify` | Geen | OTP verifiëren, ontvang session token |
| POST | `/cc/auth/logout` | Bearer | Sessie beëindigen |

### Status & Data

| Method | URL | Auth | Beschrijving |
|--------|-----|------|-------------|
| GET | `/cc/status` | Bearer | Platform status (proxy naar `/status`) |
| GET | `/cc/balance` | Bearer | Demo account balans en P&L |
| GET | `/cc/oracle` | Bearer | Market Oracle marktscan (proxy naar `/scan`) |

### Proposals

| Method | URL | Auth | Beschrijving |
|--------|-----|------|-------------|
| GET | `/cc/proposals?state=pending` | Bearer | Lijst openstaande proposals |
| POST | `/cc/proposals/{id}/confirm` | Bearer + X-OTP | Bevestig proposal met OTP |
| POST | `/cc/proposals/{id}/reject` | Bearer | Wijs proposal af |

### Trading Controls

| Method | URL | Auth | Beschrijving |
|--------|-----|------|-------------|
| POST | `/cc/pause` | Bearer | Pauzeer trading (`{"minutes": 30, "reason": "..."}`) |
| POST | `/cc/resume` | Bearer | Hervat trading |

### Backtest

| Method | URL | Auth | Beschrijving |
|--------|-----|------|-------------|
| GET | `/cc/backtest/{symbol}?interval=1h&months=3` | Bearer | Historische backtest |

### Logs

| Method | URL | Auth | Beschrijving |
|--------|-----|------|-------------|
| GET | `/cc/logs?level=ERROR&limit=100` | Bearer | Audit logs (filterbaar) |

### Health

| Method | URL | Auth | Beschrijving |
|--------|-----|------|-------------|
| GET | `/cc/health` | Geen | `{"status": "ok"}` |

## Frontend

Twee pagina's, donker thema, mobiel-vriendelijk, vanilla JS:

- `/` — Login pagina (email + OTP)
- `/dashboard` — Hoofd-dashboard met 7 secties:

| Sectie | Inhoud | Auto-refresh |
|--------|--------|-------------|
| Status | Engine state, crash_score, win_rate, actieve coins | 15s |
| Account | Balans, P&L, recente orders | 60s |
| Proposals | Lijst + confirm/reject knoppen + OTP invoer | 15s |
| Backtest | Symbol + interval selectie, resultaten per signaaltype | Handmatig |
| Oracle | Marktscan knop, JSON resultaat | Handmatig |
| Logs | Filterbaar op level, max 500 regels | 30s |
| Controls | Pause/Resume knoppen | — |

## Audit Logging

Alle acties worden gelogd in `/var/command_center/audit.log`:

```
2026-03-05 21:00:00 | user=frans@email.nl | ip=10.0.0.1 | action=confirm_proposal | result=confirmed | proposal=a1b2c3d4
2026-03-05 21:01:00 | user=frans@email.nl | ip=10.0.0.1 | action=pause_trading | result=ok | minutes=30 reason=Test
2026-03-05 21:02:00 | user=test@bad.nl | ip=10.0.0.2 | action=login_request | result=denied | email not allowed
```

Gelogde acties: `login_request`, `login_verify`, `view_status`, `view_proposals`, `confirm_proposal`, `reject_proposal`, `pause_trading`, `resume_trading`, `run_backtest`, `oracle_scan`.

## Beveiliging

- **Security headers:** CSP, X-Frame-Options: DENY, X-XSS-Protection, nosniff, strict referrer
- **CORS:** Alleen eigen domein (geen cross-origin)
- **ALLOW_LIVE:** Niet aanwezig als toggle — alleen read-only display
- **Email whitelist:** `ALLOWED_EMAIL` env var beperkt wie kan inloggen
- **Rate limiting:** 5 pogingen per 10 min per IP
- **Sessies:** SQLite, 8 uur TTL, expliciet verwijderd bij logout
- **Audit trail:** Elk verzoek gelogd met user, IP, actie, resultaat

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

## Environment variabelen

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `CONTROL_API_URL` | Ja | `http://control_api:8080` |
| `CONTROL_API_TOKEN` | Ja | Gedeeld token met control_api |
| `TELEGRAM_BOT_TOKEN` | Ja | Bot token voor OTP verzending |
| `TG_CHAT_ID` | Ja | Telegram chat ID voor OTP |
| `ALLOWED_EMAIL` | Nee | Email whitelist (leeg = alle emails) |
| `SESSION_SECRET` | Ja | Random hex string voor session signing |
| `ORACLE_URL` | Ja | `http://market_oracle_sandbox:8095` |

## Hoe te testen

```bash
# Build en start
docker compose build command_center
docker compose up -d command_center

# Health check
curl -s http://127.0.0.1:4000/cc/health | python3 -m json.tool

# Login flow
curl -s -X POST http://127.0.0.1:4000/cc/auth/request \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
# → Ontvang OTP via Telegram

curl -s -X POST http://127.0.0.1:4000/cc/auth/verify \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "code": "123456"}'
# → {"ok": true, "token": "abc123...", "expires_at": "..."}

# Status ophalen
curl -s http://127.0.0.1:4000/cc/status \
  -H "Authorization: Bearer <token>"

# Proposal bevestigen
curl -s -X POST http://127.0.0.1:4000/cc/proposals/a1b2c3d4/confirm \
  -H "Authorization: Bearer <token>" \
  -H "X-OTP: 123456"
```

## Reverse proxy (optioneel)

Voor externe toegang via HTTPS, voeg een Caddy of Nginx reverse proxy toe:

```
# Caddyfile voorbeeld
commandcenter.jouwdomein.nl {
    reverse_proxy 127.0.0.1:4000
}
```
