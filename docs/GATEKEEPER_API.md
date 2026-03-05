# Gatekeeper API — Referentie

## Overzicht

De Gatekeeper is de policy engine in `control_api`. OpenClaw Operator dient voorstellen in via deze API. Elke actie wordt gevalideerd tegen PARAM_BOUNDS, dagelijkse limieten, en vereist Telegram OTP-bevestiging (behalve flash-crash acties).

## Authenticatie

Alle endpoints vereisen `X-API-KEY` header:
```
X-API-KEY: <CONTROL_API_TOKEN>
```

---

## Endpoints

### GET /status

Volledige platform status.

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

Dien een voorstel in.

```bash
curl -s -X POST http://127.0.0.1:8080/proposals \
  -H "X-API-KEY: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "PARAM_CHANGE",
    "payload": { "rsi_buy_threshold": 32, "stoploss_pct": 3.0 },
    "reason": "Win rate te laag, RSI conservatiever",
    "requested_by": "openclaw_operator",
    "requires_confirm": true
  }'
```

**Proposal types:**

| Type | Beschrijving | Auto-apply bij flash-crash? |
|------|-------------|---------------------------|
| `PAUSE` | Pauzeer trading | Ja (zonder confirm) |
| `RESUME` | Hervat trading | Nee |
| `PARAM_CHANGE` | Wijzig trading parameters | Nee |
| `COIN_ALLOW` | Voeg coin toe aan allowlist | Nee |
| `RUN_BACKTEST` | Vraag backtest aan | Nee |
| `DEPLOY_STAGING` | Deploy naar staging | Nee |
| `NO_BUY` | Alleen verkopen, geen aankopen | Ja (zonder confirm) |
| `EXIT_ONLY` | Alleen exit posities | Ja (zonder confirm) |

**Response:**
```json
{
  "ok": true,
  "proposal_id": "a1b2c3d4",
  "type": "PARAM_CHANGE",
  "status": "pending",
  "requires_confirm": true,
  "message": "Wacht op Telegram bevestiging (OTP)"
}
```

Bij flash-crash auto-apply:
```json
{
  "ok": true,
  "proposal_id": "e5f6g7h8",
  "type": "PAUSE",
  "status": "auto_applied",
  "requires_confirm": false,
  "message": "Flash-crash actie PAUSE automatisch uitgevoerd"
}
```

---

### GET /proposals/v2?state=pending

Lijst voorstellen met status filter.

```bash
# Alle voorstellen
curl -s "http://127.0.0.1:8080/proposals/v2" -H "X-API-KEY: $TOKEN"

# Alleen pending
curl -s "http://127.0.0.1:8080/proposals/v2?state=pending" -H "X-API-KEY: $TOKEN"
```

---

### POST /proposals/{id}/confirm

Bevestig een voorstel met OTP (gestuurd via Telegram).

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

**Mogelijke fouten:**
- `403`: Ongeldig OTP
- `404`: Voorstel niet gevonden
- `429`: Max applies per dag bereikt
- `400`: PARAM_BOUNDS overtreding / voorstel niet meer pending

---

### GET /policy

Toon Gatekeeper policy regels.

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

Update macro-economische context (van Market Oracle).

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

Haal huidige macro context op.

```bash
curl -s http://127.0.0.1:8080/context/macro -H "X-API-KEY: $TOKEN"
```

---

## Policy regels

### PARAM_BOUNDS

| Parameter | Min | Max |
|-----------|-----|-----|
| `rsi_buy_threshold` | 20 | 40 |
| `rsi_sell_threshold` | 60 | 80 |
| `stoploss_pct` | 1.5% | 6.0% |
| `takeprofit_pct` | 3.0% | 12.0% |
| `position_size_base` | 1 | 5 |

Waarden buiten grenzen worden automatisch geclamped + violation gerapporteerd.

### Dagelijkse limiet

Max **3 applies per dag** (UTC). Teller reset om middernacht.

### Flash-crash auto-apply

`PAUSE`, `NO_BUY`, en `EXIT_ONLY` mogen zonder confirm als `requires_confirm: false` meegegeven wordt. Andere types vereisen altijd OTP.

### ALLOW_LIVE

Mag **NOOIT** via een proposal worden ingeschakeld. Hard geweigerd met HTTP 403.

---

## Confirm flow

```
OpenClaw → POST /proposals { type, payload, reason }
           ← { proposal_id, status: "pending" }
           → Telegram: "🔐 VOORSTEL a1b2c3d4 — OTP: 123456"

Frans → leest Telegram, kopieert OTP

OpenClaw → POST /proposals/a1b2c3d4/confirm  (X-OTP: 123456)
           ← { ok, applied: true }
           → actie uitgevoerd (pause/param change/etc)
```
