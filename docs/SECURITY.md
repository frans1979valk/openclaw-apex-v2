# Security — OpenClaw Apex Platform

## Netwerk isolatie

### Open poorten (van buitenaf bereikbaar)

| Poort | Service | Binding | Toegang |
|-------|---------|---------|---------|
| 3000 | Dashboard (Nginx) | 0.0.0.0 | Publiek (alleen HTML/JS, geen API) |
| 8080 | control_api | 0.0.0.0 | Publiek — beveiligd met X-API-KEY header |

### Localhost-only poorten (NIET publiek)

| Poort | Service | Reden |
|-------|---------|-------|
| 18789 | openclaw_gateway | Operator OS — alleen intern, Telegram is de enige UI |
| 8090 | openclaw_runtime | Agent orchestrator — intern |

**Regel:** Als je een reverse proxy (Nginx/Caddy) instelt, zet 18789 NOOIT publiek zonder auth. De gateway heeft een eigen token (`OPENCLAW_GATEWAY_TOKEN`) maar gebruik een reverse proxy met extra authenticatie als je het vanaf internet wilt bereiken.

### Docker netwerken

| Netwerk | Services | Beschrijving |
|---------|----------|--------------|
| `trade_net` | apex_engine, control_api | Trading intern netwerk |
| `agent_net` | control_api, openclaw*, dashboard, telegram bots | Agent communicatie |

`apex_engine` zit NIET op `agent_net` — OpenClaw kan de engine alleen via `control_api` bereiken.

---

## Secrets beheer

### Locatie

Alle secrets staan in `secrets/*.env`. Deze map is gitignored.

```
secrets/
├── apex.env                    ← BloFin keys + trading config
├── control_api.env             ← API token + Telegram config
├── openclaw.env                ← Kimi/Anthropic keys voor leer-agent
├── openclaw_gateway.env        ← Gateway token + Anthropic + Telegram
├── telegram_coordinator.env    ← Coordinator bot token
└── telegram_discuss.env        ← Discuss bot token
```

**Nooit committen.** Controleer met:
```bash
git status  # secrets/*.env mag NOOIT verschijnen
cat .gitignore | grep secrets
```

### .env.example templates

De `*.env.example` bestanden zijn WEL in git (geen echte values, alleen structuur).

---

## Gateway Token

De `OPENCLAW_GATEWAY_TOKEN` beschermt de WebSocket/HTTP API van de gateway.

**Genereer een nieuw token:**
```bash
openssl rand -hex 32
```

**Roteer het token:**
1. Genereer nieuw token
2. Update `secrets/openclaw_gateway.env`
3. `docker compose restart openclaw_gateway`

---

## Telegram Allowlist

OpenClaw is geconfigureerd met `dmPolicy: "allowlist"` — alleen jouw User ID mag de bot besturen.

```json
"dmPolicy": "allowlist",
"allowedIds": ["${TG_ALLOWED_USER_ID}"]
```

**Voeg iemand toe:** Update `TG_ALLOWED_USER_ID` in `secrets/openclaw_gateway.env` (meerdere IDs: komma-gescheiden) en herstart de gateway.

**Controleer:** Andere Telegram accounts kunnen de bot NIET gebruiken.

---

## Wat OpenClaw NOOIT mag

Deze beperkingen zijn hardcoded in de gatekeeper skill en de control_api:

| Verbod | Afdwinging |
|--------|-----------|
| Exchange API aanroepen | Gatekeeper skill verbiedt het expliciet; tool scripts praten alleen met control_api |
| BloFin keys gebruiken | OpenClaw container heeft deze keys NOOIT in zijn env |
| `ALLOW_LIVE=true` instellen | Hardcoded `false` in apex.env; geen enkel tool script raakt deze variable |
| Parameters buiten PARAM_BOUNDS | `tool_propose_params.py` clamp automatisch + error bij overschrijding |
| > 3 apply acties per dag | Afgedwongen door `MAX_APPLIES_PER_DAY=3` in control_api |
| Apply zonder bevestiging | control_api `CONFIRM_REQUIRED=true` blokkeert onbevestigde applies |

---

## PARAM_BOUNDS (hardcoded veiligheidslimieten)

Gedefinieerd in `openclaw_tools/registry.json` en afgedwongen in `tool_propose_params.py`:

| Parameter | Min | Max |
|-----------|-----|-----|
| `rsi_buy_threshold` | 20 | 40 |
| `rsi_sell_threshold` | 60 | 80 |
| `stoploss_pct` | 1.5 | 6.0 |
| `takeprofit_pct` | 3.0 | 12.0 |
| `position_size_base` | 1 | 5 |

Aanpassen vereist code-wijziging in `tool_propose_params.py` — niet via env vars.

---

## Confirm policy

Twee modi in control_api:

| Modus | Gedrag |
|-------|--------|
| `CONFIRM_REQUIRED=true` (default) | Elk `apply` blokkeert totdat `/ok <id>` gestuurd wordt via Telegram |
| `CONFIRM_REQUIRED=false` | Agent kan automatisch toepassen (alleen voor geautomatiseerde test-omgevingen) |

**Flash-crash uitzondering:** `tool_pause_trading` en `tool_resume_trading` zijn altijd onmiddellijk — ze vereisen geen confirm. Parameters toepassen blijft altijd confirm-required.

---

## API Key overzicht

| Service | Key type | Locatie | Heeft trading bevoegdheid? |
|---------|----------|---------|---------------------------|
| apex_engine | BloFin API key/secret/passphrase | secrets/apex.env | Ja (demo only) |
| control_api | CONTROL_API_TOKEN (intern) | secrets/control_api.env | Gatekeeper |
| openclaw_gateway | ANTHROPIC_API_KEY (Sonnet) | secrets/openclaw_gateway.env | Nee |
| openclaw_gateway | OPENCLAW_GATEWAY_TOKEN | secrets/openclaw_gateway.env | Nee |
| openclaw (leer-agent) | KIMI_API_KEY, ANTHROPIC_API_KEY | secrets/openclaw.env | Nee |

**OpenClaw gateway heeft NOOIT BloFin keys.**

---

## Versie pinning & supply chain

- **OpenClaw submodule gepind op v2026.3.2** (bevat ClawJacked fix uit v2026.2.25)
- Dockerfile.gateway controleert minimale versie bij build: `< 2026.2.25` → hard fail
- **Geen marketplace skills:** `skills.allowBundled` beperkt tot `["browser", "github"]`
- Alle custom skills komen uit `./skills/` (gevendord in onze repo)
- Skills worden read-only gemount in de container (`./skills:/workspace/skills:ro`)
- Update procedure: `git submodule update --remote`, tag controleren, rebuild

---

## Audit & logging

Alle tool-aanroepen worden gelogd in `/var/apex/openclaw_tools.log` (gemount volume `apex_data`).

Bekijk live:
```bash
docker compose exec control_api tail -f /var/apex/openclaw_tools.log
```

Bekijk gateway logs:
```bash
docker compose logs -f openclaw_gateway
```

---

## Checklist bij go-live

- [ ] `secrets/openclaw_gateway.env` aangemaakt met echte waarden
- [ ] `OPENCLAW_GATEWAY_TOKEN` gegenereerd met `openssl rand -hex 32`
- [ ] Nieuwe Telegram bot aangemaakt via @BotFather
- [ ] `TG_ALLOWED_USER_ID` ingesteld op jouw eigen ID
- [ ] Poort 18789 is NIET publiek bereikbaar (check: `ss -tlnp | grep 18789` → moet `127.0.0.1` tonen)
- [ ] `ALLOW_LIVE=false` in `secrets/apex.env` (bevestig bij overstap naar live)
- [ ] secrets/ staat in `.gitignore` en is niet gepushed
