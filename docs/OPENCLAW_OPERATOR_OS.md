# OpenClaw Operator-OS — Handleiding

## Wat is dit?

OpenClaw Gateway is de "Operator OS" laag van het Apex platform. Het is de [openclaw/openclaw](https://github.com/openclaw/openclaw) TypeScript framework dat draait als een Telegram-gestuurde AI-assistent bovenop de trading stack.

```
Frans (Telegram DM) → OpenClaw Gateway (poort 18789, localhost)
                              ↓
                   Gatekeeper Skill (Python tools)
                              ↓ HTTP
                      control_api (:8080)
                              ↓
                     apex_engine (BloFin demo)
```

**OpenClaw heeft nooit:** exchange keys, directe trade-toegang, of ALLOW_LIVE=true.

---

## Eenmalige installatie

### Stap 1: Maak een nieuwe Telegram bot aan

1. Open Telegram en zoek **@BotFather**
2. Stuur `/newbot`
3. Naam: `OpenClaw Operator` (of eigen keuze)
4. Username: `openclaw_operator_bot` (of eigen keuze, eindigt op `_bot`)
5. Kopieer het token dat je krijgt (formaat: `123456:ABCDEF...`)

### Stap 2: Vind je eigen Telegram User ID

1. Open Telegram en zoek **@userinfobot** of **@getidsbot**
2. Stuur `/start`
3. Noteer je **User ID** (getal, bijv. `7381250590`)

### Stap 3: Maak de secrets file aan

```bash
cp secrets/openclaw_gateway.env.example secrets/openclaw_gateway.env
```

Vul in:
```
OPENCLAW_GATEWAY_TOKEN=<genereer met: openssl rand -hex 32>
ANTHROPIC_API_KEY=<jouw Anthropic key>
TELEGRAM_BOT_TOKEN=<token van stap 1>
TG_ALLOWED_USER_ID=<jouw User ID van stap 2>
CONTROL_API_URL=http://control_api:8080
CONTROL_API_TOKEN=changeme-strong-token
```

### Stap 4: Bouw en start

```bash
# Bouw de gateway (duurt 3-8 minuten bij eerste keer)
docker compose build openclaw_gateway

# Start alles
docker compose up -d

# Controleer of gateway draait
curl http://127.0.0.1:18789/health
```

### Stap 5: Pairkoppeling Telegram

1. Stuur een DM naar jouw nieuwe bot in Telegram
2. De bot stuurt een koppelingsverzoek
3. Accepteer — daarna kun je alles besturen

---

## Dag-tot-dag gebruik

### Status opvragen

Stuur naar de bot:
```
status
```
Of:
```
wat is de huidige markt?
```

OpenClaw roept `tool_status` aan en antwoordt met actuele signalen, crash_score en win_rate.

### Backtest uitvoeren

```
backtest XRP-USDT
```
Of specifiek:
```
backtest XRP-USDT 4h
```

### Parameter voorstel indienen

Vraag de agent om een analyse:
```
analyseer de win_rate en stel betere parameters voor als dat nodig is
```

De agent:
1. Roept `tool_status` aan
2. Voert een backtest uit
3. Dient een voorstel in als profit_factor > 1.15
4. Stuurt jou: "Bevestig met /ok `<proposal_id>`"

### Voorstel bevestigen

```
/ok abc123
```

Dit geldt als jouw "JA" — de agent past de parameters toe.

### Noodstop

```
stop
```
Of:
```
zet trading op pauze voor 60 minuten, te veel volatiliteit
```

### Trading hervatten

```
hervat trading
```

---

## Agents wisselen

OpenClaw heeft 3 gespecialiseerde agents. De **operator_risk_agent** is standaard actief via Telegram.

Om te wisselen:
```
schakel naar research agent
```
```
schakel naar builder agent
```
```
schakel terug naar risk
```

### Agent bevoegdheden

| Agent | Kan lezen | Kan schrijven | Kan uitvoeren |
|-------|-----------|---------------|---------------|
| `operator_risk_agent` (standaard) | status, news, backtest | propose_params | pause, resume (+ apply na JA) |
| `research_agent` | status, news, backtest, browser | — | — |
| `builder_agent` | status, news, backtest, git | propose_params, git commits | — (nooit deployen zonder voorstel) |

---

## Confirm Flow

### Normaal

```
Jij: "stel betere stoploss voor"
Agent: analyseert → backtest → proposal_id: abc123
       "Bevestig met /ok abc123"
Jij: "/ok abc123"
Agent: voert apply uit → "Parameters bijgewerkt ✓"
```

### Flash-Crash (automatisch)

De agent scant actief op gevaarlijke condities en **pauzeert automatisch** (zonder jouw bevestiging) bij:

| Conditie | Actie | Duur |
|----------|-------|------|
| crash_score > 70 | Auto-pause | 30 min |
| crash_score > 85 | Auto-pause | 60 min |
| win_rate < 40% (> 20 trades) | Auto-pause | 60 min |
| 2+ BTC_CASCADE events (1 uur) | Auto-pause | 45 min |
| FLASH_CRASH event | Auto-pause | 20 min |

Na een auto-pause stuurt de agent altijd een melding: reden + duur.

### Wat NOOIT automatisch

- `tool_apply_proposal` (parameter toepassen) — altijd JA nodig
- `ALLOW_LIVE=true` — verboden in code
- Directe exchange aanroep — verboden in code

---

## Gateway status controleren

Vanuit de VPS (shell):
```bash
# Health endpoint
curl http://127.0.0.1:18789/health

# Container logs
docker compose logs -f openclaw_gateway

# Skills lijst in container
docker compose exec openclaw_gateway node openclaw.mjs skills list

# Gateway status
docker compose exec openclaw_gateway node openclaw.mjs gateway status
```

---

## Bestanden overzicht

```
openclaw_config/
└── openclaw.json          ← hoofd-configuratie (gemount read-only)

skills/
└── gatekeeper/
    └── SKILL.md           ← custom Gatekeeper skill

openclaw_tools/
└── scripts/               ← Python tool scripts (gemount als /workspace/tools/)
    ├── tool_status.py
    ├── tool_run_backtest.py
    ├── tool_propose_params.py
    ├── tool_apply_proposal.py
    ├── tool_pause_trading.py
    ├── tool_resume_trading.py
    └── tool_fetch_news.py

secrets/
├── openclaw_gateway.env.example   ← template
└── openclaw_gateway.env           ← echte keys (NOOIT in git)

Dockerfile.gateway                 ← bouwt openclaw/openclaw TypeScript
```

---

## Troubleshooting

**Bot reageert niet:**
```bash
docker compose logs openclaw_gateway | tail -50
```
Check: bot token correct? TG_ALLOWED_USER_ID correct? Container draait?

**"Unauthorized" bij control_api calls:**
Check `CONTROL_API_TOKEN` in `secrets/openclaw_gateway.env` — moet overeenkomen met `secrets/control_api.env`.

**Build mislukt (pnpm errors):**
```bash
docker compose build --no-cache openclaw_gateway
```
Of check Node.js versie in de container (vereist 22.12.0+).

**Skills niet gevonden:**

1. Controleer dat `./skills/gatekeeper/SKILL.md` bestaat op de host:
```bash
cat skills/gatekeeper/SKILL.md | head -5
```

2. Controleer dat het volume correct gemount is in de container:
```bash
docker compose exec openclaw_gateway ls -la /workspace/skills/gatekeeper/
```

3. Controleer `extraDirs` in config:
```bash
docker compose exec openclaw_gateway cat /root/.openclaw/openclaw.json | grep -A3 extraDirs
```

4. Full restart vereist na skill toevoeging (config reload is niet genoeg):
```bash
docker compose restart openclaw_gateway
```

5. Fallback: als `extraDirs` niet werkt, kopieer skills naar `~/.openclaw/skills/` in de container:
```bash
docker compose exec openclaw_gateway cp -r /workspace/skills/* /root/.openclaw/skills/ 2>/dev/null
docker compose restart openclaw_gateway
```

**Health endpoint stuurt HTML i.p.v. JSON:**
Bekende bug in sommige OpenClaw versies. Check met:
```bash
curl -s http://127.0.0.1:18789/health | head -1
```
Als je `<html` ziet: de gateway control UI overschrijft `/health`. Gebruik dan:
```bash
docker compose exec openclaw_gateway node openclaw.mjs gateway status
```
