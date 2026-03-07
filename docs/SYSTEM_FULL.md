# SYSTEM_FULL.md — Volledige Systeemdocumentatie Apex Trading Platform

Versie: 2026-03-06 | Modus: demo | Platform: Docker Compose op VPS

---

## 1. Architectuuroverzicht

### 1.1 Services

| Service | Poort | Netwerk | Functie |
|---------|-------|---------|---------|
| `apex_engine` | — (intern) | trade_net | Trading engine: signalen, orders, crash detectie |
| `control_api` | 0.0.0.0:8080 | trade_net + agent_net | Gatekeeper API, policy engine, authenticatie, SSE stream |
| `dashboard` | 0.0.0.0:3000 | agent_net | Nginx static SPA: login + live dashboard |
| `openclaw_gateway` | 127.0.0.1:18789 | agent_net | OpenClaw TypeScript gateway (Telegram AI operator) |
| `openclaw_runtime` | 127.0.0.1:8090 | agent_net | Python FastAPI runtime voor OpenClaw tool scripts |
| `market_oracle_sandbox` | 127.0.0.1:8095 | agent_net | Geisoleerde macro-analyse (RSS + Yahoo Finance) |
| `openclaw` | — (intern) | agent_net | Legacy Python agent (learn + backtest loop) |
| `tg_coordinator_bot` | — (intern) | agent_net | Telegram: automatische 5-min marktrapporten |
| `tg_discuss_bot` | — (intern) | agent_net | Telegram: interactieve bot met trading controls |
| `jojo_analytics` | 127.0.0.1:8097 | agent_net | TA indicators + DB query service voor Jojo1 |
| `kimi_pattern_agent` | 127.0.0.1:8098 | agent_net | Nachtelijke patroonanalyse via Kimi AI |
| `indicator_engine` | 127.0.0.1:8099 | trade_net | Historische OHLCV import + pattern matching + signalen |

### 1.2 Communicatie tussen services

```
Frans (Telegram)
  |
  +-- tg_discuss_bot -------> control_api :8080 (REST)
  |                               |
  +-- openclaw_gateway :18789 --->+  (REST, via gatekeeper skill)
  |                               |
  +-- tg_coordinator_bot -------->+  (GET /state/latest, elke 5 min)
                                  |
                            control_api
                              |       |
                    (trade_net)|     (agent_net)
                              |       |
                        apex_engine   market_oracle_sandbox :8095
                              |
                        BloFin Demo API (extern)
                        Binance API (extern, alleen data)

Dashboard (browser :3000)
  |
  +-- GET /stream (SSE) -------> control_api :8080
  +-- GET /state/latest --------> control_api :8080
  +-- GET /market/prices -------> control_api :8080 (proxy naar exchanges)
```

**Gedeeld volume:** `apex_data` gemount op `/var/apex` bij apex_engine, control_api, openclaw_runtime en openclaw_gateway. Bevat:
- `apex.db` (SQLite database)
- `bot_state.json` (huidige coin states, signalen, agent verdicts)
- `trading_halt.json` (halt/pause status)
- `approved_coins.json` (coin allowlist)

### 1.3 Docker Compose structuur

```yaml
networks:
  trade_net:    # apex_engine <-> control_api
  agent_net:    # control_api <-> alle agent/UI services

volumes:
  apex_data:            # /var/apex (gedeeld state)
  openclaw_workspace:   # /workspace (legacy openclaw agent)
```

**Restart policy:** Alle services `unless-stopped`.

**Resource limits:** Alleen `market_oracle_sandbox` heeft expliciete limieten: 0.5 CPU, 256 MB RAM.

### 1.4 VPS vs lokaal

Alle services draaien op de VPS via Docker Compose. Er is geen lokale component. De dashboard is bereikbaar via `http://<VPS_IP>:3000`, control_api via `http://<VPS_IP>:8080`. Gateway (18789), runtime (8090) en oracle (8095) zijn alleen op localhost gebonden.

---

## 2. control_api (Gatekeeper)

### 2.1 Alle endpoints

#### Authenticatie

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| POST | `/auth/request` | `{"email": "..."}` | `{"ok": true, "message": "Code verstuurd via Telegram"}` | Geen |
| POST | `/auth/verify` | `{"email": "...", "code": "123456"}` | `{"ok": true, "token": "hex64", "expires_at": "ISO8601"}` | Geen |

#### Status & Health

| Method | URL | Response | Auth |
|--------|-----|----------|------|
| GET | `/health` | `{"ok": true}` | Geen |
| GET | `/status` | Volledige platform status (zie 2.5) | X-API-KEY |
| GET | `/state/latest` | Huidige bot_state.json | X-API-KEY |
| GET | `/stream?token=...` | SSE stream (elke 2s bij wijziging) | Query token |

#### Trading Control

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| POST | `/trading/halt` | — | `{"status": "halted"}` | X-API-KEY |
| POST | `/trading/resume` | — | `{"status": "resumed"}` | X-API-KEY |
| POST | `/trading/pause` | `{"minutes": 30, "reason": "..."}` | `{"status": "paused", "paused_until": "ISO8601"}` | X-API-KEY |
| GET | `/trading/status` | — | `{"halted": bool, "paused_until": "...", "reason": "..."}` | X-API-KEY |
| POST | `/trading/answer` | `{"q_id": "...", "antwoord": "ok\|stop\|skip"}` | `{"q_id": "...", "antwoord": "..."}` | X-API-KEY |
| GET | `/trading/answer?q_id=...` | — | `{"q_id": "...", "antwoord": "..."}` (destructive read) | X-API-KEY |

#### Gatekeeper Proposals (v2)

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| POST | `/proposals` | ProposalV2 body (zie 2.4) | `{"ok": true, "proposal_id": "hex8", "type": "...", "status": "pending\|auto_applied"}` | X-API-KEY |
| GET | `/proposals/v2?state=pending` | — | Array van proposals | X-API-KEY |
| POST | `/proposals/{id}/confirm` | Header `X-OTP: 123456` | `{"ok": true, "applied": true, "applies_today": N}` | X-API-KEY + X-OTP |

#### Legacy Proposals

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| GET | `/proposals` | — | Array van proposals (v1) | X-API-KEY |
| POST | `/config/propose` | `{"agent": "...", "params": {}, "reason": "..."}` | `{"ok": true, "proposal_id": "..."}` | X-API-KEY |
| POST | `/proposals/{id}/apply` | — | `{"ok": true, "applied": "..."}` | X-API-KEY |

#### Market Data

| Method | URL | Response | Auth |
|--------|-----|----------|------|
| GET | `/market/prices/{symbol}` | Multi-exchange prijzen + consensus | X-API-KEY |
| GET | `/history/prices/{symbol}?hours=24` | Array: ts, price, rsi, signal, tf_bias | X-API-KEY |
| GET | `/history/crash/{symbol}?hours=48` | Array: ts, score | X-API-KEY |
| GET | `/history/events?hours=72&event_type=&symbol=` | Array: ts, type, severity, description | X-API-KEY |
| GET | `/history/summary/{symbol}` | AI context: price_24h, crash_24h, events, signal_stats | X-API-KEY |

#### Backtesting

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| GET | `/backtest/{symbol}?interval=1h&limit=500` | — | Quick backtest: win_rate, profit_factor, max_drawdown, sharpe | X-API-KEY |
| GET | `/backtest/historical/{symbol}?interval=1h&months=6` | — | Full backtest: signalen per type met 1h/4h/24h stats | X-API-KEY |
| GET | `/backtest/historical/{symbol}/signals?limit=100` | — | Individuele signaal records | X-API-KEY |
| POST | `/backtest/run` | `{"symbol": "...", "interval": "1h"}` | `{"job_id": "...", "status": "running"}` | X-API-KEY |
| GET | `/backtest/result/{job_id}` | — | `{"status": "done\|running\|error", "result": {...}}` | X-API-KEY |

#### Performance & Balance

| Method | URL | Response | Auth |
|--------|-----|----------|------|
| GET | `/balance` | Demo account: start_usdt, balance, pnl, win_rate, orders | X-API-KEY |
| GET | `/signal-performance?limit=50` | Historische signalen met P&L per timeframe | X-API-KEY |
| GET | `/metrics/performance?limit=100` | Geaggregeerd: overall, by_signal, by_coin, crash_24h | X-API-KEY |

#### Coin Management

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| GET | `/coins/approved` | — | `{"approved": [...], "pending": [...], "rejected": [...]}` | X-API-KEY |
| POST | `/coins/approved` | `{"symbol": "BTCUSDT", "action": "approve\|reject\|pending"}` | `{"ok": true, "coins": {...}}` | X-API-KEY |
| POST | `/coins/pending` | `{"symbol": "BTCUSDT"}` | `{"ok": true, "status": "pending"}` | X-API-KEY |

#### Context & Policy

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| POST | `/context/macro` | Oracle JSON output | `{"ok": true}` | X-API-KEY |
| GET | `/context/macro` | — | Volledige macro context | X-API-KEY |
| GET | `/policy` | — | param_bounds, max_applies, flashcrash_actions, proposal_types | X-API-KEY |
| GET | `/policy/confirm` | — | `{"confirm_required": true}` | X-API-KEY |
| POST | `/policy/confirm` | `{"confirm_required": bool}` | `{"confirm_required": bool, "status": "ok"}` | X-API-KEY |

#### ClawBot Model

| Method | URL | Request | Response | Auth |
|--------|-----|---------|----------|------|
| GET | `/clawbot/model` | — | `{"model": "haiku", "is_premium": false}` | X-API-KEY |
| POST | `/clawbot/model` | `{"model": "haiku\|sonnet"}` | `{"model": "...", "status": "ok"}` | X-API-KEY |

### 2.2 Authenticatie

Twee mechanismen:

**1. Statische API key:**
```
Header: X-API-KEY: <CONTROL_API_TOKEN>
```
Vergelijkt direct met `os.environ["CONTROL_API_TOKEN"]`. Gebruikt door services onderling en door de Telegram bots.

**2. Session token (dashboard):**
- Gebruiker vraagt OTP aan via `POST /auth/request` (email)
- 6-cijferige code wordt via Telegram Bot API gestuurd naar `TG_CHAT_ID`
- Code is 10 minuten geldig, opgeslagen in SQLite tabel `otp_codes`
- Na verificatie (`POST /auth/verify`): session token (64 hex chars), 24 uur geldig
- Token opgeslagen in SQLite tabel `sessions`
- Dashboard stuurt token als `X-API-KEY` header of als `?token=` query parameter (SSE)

```python
# Validatie volgorde in auth():
1. x_api_key == CONTROL_API_TOKEN  → OK (statische key)
2. SELECT expires_at FROM sessions WHERE token = x_api_key  → OK als niet verlopen
3. Beide falen → HTTP 401
```

### 2.3 Policy engine (hardcoded regels)

**PARAM_BOUNDS:**

| Parameter | Min | Max |
|-----------|-----|-----|
| `rsi_buy_threshold` | 20 | 40 |
| `rsi_sell_threshold` | 60 | 80 |
| `stoploss_pct` | 1.5 | 6.0 |
| `takeprofit_pct` | 3.0 | 12.0 |
| `position_size_base` | 1 | 5 |

Waarden buiten grenzen worden automatisch **geclamped** (niet geweigerd). Violations worden gerapporteerd maar blokkeren het voorstel niet.

**Overige regels:**
- `MAX_APPLIES_PER_DAY = 3` — teller reset om 00:00 UTC
- `FLASHCRASH_AUTO_ACTIONS = {"PAUSE", "NO_BUY", "EXIT_ONLY"}` — mogen zonder OTP bevestiging
- `PROPOSAL_TYPES = {"PAUSE", "RESUME", "PARAM_CHANGE", "COIN_ALLOW", "RUN_BACKTEST", "DEPLOY_STAGING"}`
- `ALLOW_LIVE` — **HARDCODED VERBOD.** Elke poging via proposal → HTTP 403

### 2.4 Proposal flow

**Indienen (`POST /proposals`):**
```json
{
  "type": "PARAM_CHANGE",
  "payload": {"rsi_buy_threshold": 32, "stoploss_pct": 3.0},
  "reason": "Win rate te laag, RSI conservatiever",
  "requested_by": "openclaw_operator",
  "requires_confirm": true
}
```

**Flow:**
```
1. Valideer type ∈ PROPOSAL_TYPES
2. Als PARAM_CHANGE: valideer payload tegen PARAM_BOUNDS (clamp + rapporteer)
3. Check: auto_apply = (type ∈ FLASHCRASH_AUTO_ACTIONS) AND (requires_confirm = false)
4. Genereer proposal_id (secrets.token_hex(4) → 8 hex chars)
5. Genereer OTP (random.randint(100000, 999999) → 6 cijfers)
6. Sla op in SQLite tabel proposals_v2 (status: "pending" of "auto_applied")
7. Sla OTP op in memory dict _confirm_tokens[proposal_id]
8. Stuur Telegram bericht met proposal details + OTP code

Als auto_apply:
9. Voer _execute_proposal() direct uit
10. Skip bevestiging stap
```

**Bevestigen (`POST /proposals/{id}/confirm`):**
```
1. Lees X-OTP header
2. Vergelijk met _confirm_tokens[proposal_id]  → 403 bij mismatch
3. Check dagelijkse limiet (_check_applies_limit())  → 429 bij overschrijding
4. Laad proposal uit DB, check status = "pending"  → 400 als niet pending
5. Als PARAM_CHANGE: hervalideer PARAM_BOUNDS
6. Block ALLOW_LIVE payload  → 403
7. Update DB: status="confirmed", confirmed_at, applied_at
8. Increment _applies_today["count"]
9. Delete OTP uit memory
10. _execute_proposal(proposal_id, type, payload, reason)
```

**Uitvoering per type:**

| Type | Actie |
|------|-------|
| `PAUSE` | Zet `paused_until` op now + N minuten, schrijf `/var/apex/trading_halt.json` |
| `RESUME` | Wis halt/pause state, schrijf trading_halt.json |
| `PARAM_CHANGE` | Lees `bot_state.json`, update `config_overrides` dict, schrijf terug |
| `COIN_ALLOW` | Gelogd, geen directe executie |
| `RUN_BACKTEST` | Gelogd, geen directe executie |
| `DEPLOY_STAGING` | Gelogd, geen directe executie |

### 2.5 GET /status response

```json
{
  "mode": "demo",
  "allow_live": false,
  "trading": {
    "halted": false,
    "paused_until": null,
    "reason": ""
  },
  "last_signals": {"BTC-USDT": "HOLD", "ETH-USDT": "BUY"},
  "open_positions": [],
  "crash_max_24h": 45,
  "overall_win_rate": 62.5,
  "risk_flags": [],
  "macro_context": {},
  "applies_today": 1,
  "max_applies_per_day": 3
}
```

**Risk flags worden automatisch berekend:**
- `crash_max_24h > 70` → `"HIGH_CRASH_SCORE:75"`
- `overall_win_rate < 40` → `"LOW_WIN_RATE:35%"`
- `halted = true` → `"TRADING_HALTED"`
- `paused_until` gezet → `"PAUSED_UNTIL:2026-03-05T21:00:00Z"`

---

## 3. Apex Trading Engine

### 3.1 Strategie

De engine gebruikt **5 onafhankelijke technische indicatoren** die samen een signaal genereren:

**Indicator 1: RSI-MACD Bounce**
- Voorwaarden: RSI(14) < 32 AND MACD histogram > 0 AND MACD lijn > Signaal lijn AND wick-to-ATR ratio < 0.6
- Genereert: BUY
- Confidence: `min(95, max(50, abs(50-RSI)*1.5 + abs(MACD_hist)*500))`

**Indicator 2: Bollinger Squeeze Explosion**
- Voorwaarden: BB Width < 2.5 (squeeze) AND prijs breekt door upper/lower band
- Genereert: BUY (long) of SELL (short)
- Confidence: `min(95, max(50, (2.5 - BB_width)*30))`

**Indicator 3: Golden Cross Momentum**
- Voorwaarden: EMA21 > EMA55 > EMA200 (bullish) of omgekeerd (bearish)
- Genereert: BUY of SELL
- Strength: `abs((EMA21 - EMA55) / EMA55 * 100) * 40`

**Indicator 4: Stochastic RSI Divergence**
- BUY: StochRSI K < 20 AND K > D AND RSI < 45
- SELL: StochRSI K > 80 AND K < D AND RSI > 55

**Indicator 5: ADX Momentum Breakout**
- Voorwaarden: ADX > 25 AND +DI > -DI (of omgekeerd)
- Confidence: `min(95, max(50, ADX*2))`

### 3.2 Gecombineerde signalen (prioriteitsvolgorde)

| Prioriteit | Signaal | Voorwaarden |
|------------|---------|-------------|
| 1 | `PERFECT_DAY` | Alle 5 indicatoren bullish tegelijk |
| 2 | `BREAKOUT_BULL` | Prijs > BB upper + RSI > 50 + volume > 1.5x gemiddeld |
| 3 | `MOMENTUM` | Golden cross + 50 < RSI < 65 + MACD hist > 0 + ADX long |
| 4 | `DANGER` | RSI > 72 + MACD hist < 0 + prijs < SAR, OF prijs < BB lower + RSI < 35 + ADX > 20 |
| 5 | `BUY` | Eender welke indicator bullish |
| 6 | `SELL` | Eender welke indicator bearish |
| 7 | `HOLD` | Geen signaal (default) |

### 3.3 Multi-timeframe bevestiging

Controleert 1h, 4h en 1d trends met gewichten: 1h=0.5, 4h=0.35, 1d=0.15.

Bullish TF = EMA21 > EMA55 AND MACD hist > 0 AND RSI < 70.

- **Downgrade:** BUY → HOLD als hogere timeframe bearish
- **Upgrade:** BUY → MOMENTUM als hogere TF bullish (score >= 75) EN RSI < 40

### 3.4 Coins in scope

**Permanent whitelist (SAFE_COINS):**
```
BTC, ETH, XRP, BNB, SOL, ADA, DOGE, AVAX, DOT, LINK, LTC, ATOM, NEAR,
UNI, AAVE, XLM, ALGO, INJ, OP, ARB, APT, SEI, SUI, TIA, FET, RENDER,
JUP, FTM, SAND, MANA, VET, HBAR, GRT, MATIC, FIL, PEPE, SHIB, BONK, WIF
```
Alle als USDT-paren op BloFin.

**Selectie pipeline:**
1. Filter op BloFin beschikbaarheid
2. Filter op minimaal $5M 24h volume
3. Filter: geen tokenized stocks (PLTR, COIN, AMZN, etc.)
4. Kimi AI selecteert TOP_N (default 5) beste coins voor short-term trades
5. Nieuwe coins (niet in SAFE_COINS) worden `pending` — vereisen Telegram goedkeuring
6. Fallback bij Kimi falen: top volume safe coins

**Scan interval:** Elke 300 seconden (5 minuten).

### 3.5 Signaal generatie pipeline

```
Elke 10 seconden per coin:
  1. Fetch live prijs (Binance)
  2. Exchange Intel: gewogen consensus Coinbase(0.35) + Binance(0.25) +
     Bybit(0.20) + OKX(0.12) + Kraken(0.08)
  3. Pre-Crash Detector: bereken crash_score (0-100)
     → score >= 60: kopen verboden (IJZEREN WET)
  4. BTC Cascade Detector: BTC > 3% drop in 5 min
     → cascade SHORT: ETH(2min), BNB(4min), SOL(5min), XRP(8min)
  5. Fetch 300x 5-min OHLCV candles van Binance
  6. Bereken alle 5 indicatoren
  7. Genereer base_signal (PERFECT_DAY / BREAKOUT_BULL / ... / HOLD)
  8. Multi-TF bevestiging (1h/4h/1d) → upgrade/downgrade
  9. IJZEREN WET: forceer DANGER als crash_score >= 60
  10. Order placement als signaal BUY + safe_to_buy + cooldown voorbij
      → size "2" bij PERFECT_DAY, anders "1"
      → ORDER_COOLDOWN = 120 seconden per coin
```

### 3.6 crash_score berekening

Pre-crash score (0-100) bestaat uit 4 gewogen componenten:

| Component | Gewicht | Drempel | Formule |
|-----------|---------|---------|---------|
| Orderbook Imbalance | 30% | bid_ratio < 35% | `min(1.0, (0.35 - ratio) / 0.35 * 1.5)` |
| Volume Divergence | 25% | vol >= 2x avg & prijs daalt | `min(1.0, (vol_ratio/2 - 1)*0.5 + abs(price_change)*10)` |
| RSI Overbought | 20% | RSI >= 75 | `min(1.0, (RSI - 75) / 25)` |
| Price Momentum | 25% | drop <= -1.5% in 3 candles | `min(1.0, abs(pct_drop) / 1.5 * 0.7)` |

**Drempels:**
- `>= 60`: Kopen verboden (IJZEREN WET)
- `>= 80`: CRITICAL — alleen shorts
- Orderbook wordt max 1x per 30 seconden opgehaald

**Functie:** `detector.score(symbol, price, rsi, volume)` retourneert 0-100.

### 3.7 Demo vs live modus

**Demo modus (huidige configuratie):**
- Gebruikt BloFin Demo Trading API (`https://demo-trading-openapi.blofin.com`)
- Echte orders op demo server (geen echt geld)
- Authenticatie met HMAC-SHA256 (API key + secret + passphrase)
- Max order size: $50 USDT
- Virtueel startkapitaal: $1000
- Trades sluiten automatisch na 1 uur
- P&L tracking op 15 min, 1h en 4h marks

**Live modus (geblokkeerd):**
```python
# main.py — 3 harde checks bij opstart:
if TRADING_MODE != "demo":
    raise RuntimeError("TRADING_MODE must be demo.")
if EXECUTOR_MODE != "blofin_demo":
    raise RuntimeError("EXECUTOR_MODE must be blofin_demo.")
if ALLOW_LIVE:
    raise RuntimeError("ALLOW_LIVE must stay false.")
```
Alle drie moeten falen voordat de engine überhaupt start. Er is geen pad naar live trading zonder code-wijzigingen.

### 3.8 Timing constanten

| Constante | Waarde | Doel |
|-----------|--------|------|
| `KIMI_SCAN_INTERVAL` | 300s (5 min) | Coin selectie |
| `AGENT_INTERVAL` | 1800s (30 min) | AI agent workflow |
| `INDICATOR_INTERVAL` | 5m candles | Technische analyse |
| `ORDER_COOLDOWN` | 120s | Tussen orders per coin |
| `SIGNAL_LOG_COOLDOWN` | 900s (15 min) | Tussen signaal logs |
| `PRE_CRASH_BUY_BLOCK` | 60 | Crash score drempel |
| `NEWS_POLL_INTERVAL` | 120s | CryptoPanic polling |

### 3.9 Database tabellen

| Tabel | Doel |
|-------|------|
| `signal_performance` | Entry prijs, P&L op 15m/1h/4h |
| `market_context` | Multi-TF RSI, bias (voor AI learning) |
| `demo_account` | Virtuele trades met P&L |
| `demo_balance` | $1000 startkapitaal tracking |
| `price_snapshots` | Prijs, RSI, signaal elke 5 min |
| `crash_score_log` | Historische crash scores (elke min als > 30) |
| `exchange_consensus_log` | Prijs divergentie tussen exchanges (elke 10 min) |
| `market_events` | BTC cascades, flash crashes, news alerts |

### 3.10 State bestanden

| Bestand | Pad | Doel |
|---------|-----|------|
| `apex.db` | `/var/apex/apex.db` | SQLite database |
| `bot_state.json` | `/var/apex/bot_state.json` | Huidige coin states + signalen |
| `trading_halt.json` | `/var/apex/trading_halt.json` | Halt/pause status (geschreven door control_api) |
| `approved_coins.json` | `/var/apex/approved_coins.json` | Coin allowlist |

---

## 4. Dashboard (poort 3000)

### 4.1 Technologie

Plain HTML5 + vanilla JavaScript. Geen framework (geen React/Next.js). Donker thema. Served door `nginx:alpine` op poort 3000.

Bestanden:
- `dashboard/login.html` — OTP login pagina
- `dashboard/index.html` — Hoofd-dashboard (925 regels)
- `dashboard/nginx.conf` — SPA routing, cache-control headers

### 4.2 Wat het dashboard toont

- **Live ticker:** BTC, ETH, SOL, BNB, XRP — elke 3 seconden via Binance
- **Coin overview:** Signalen (BUY/SELL/HOLD/PERFECT_DAY/BREAKOUT_BULL/MOMENTUM)
- **Technische indicatoren:** RSI, MACD, EMA, Bollinger Bands, ATR
- **Pre-crash score:** 0-100 schaal met waarschuwingen
- **Multi-exchange vergelijking:** Coinbase, Binance, Bybit, OKX, Kraken, BloFin met gewogen consensus
- **Demo account:** Balans (start $1000), P&L, win-rate
- **Signal performance:** Win-rate en P&L per timeframe (15m/1h/4h)
- **Flash crash detector:** Volatiliteits-triggers
- **AI agent beslissingen:** Research → Strategy → Risk → Verify workflow
- **Historische backtest:** Filterbaar op signaaltype en periode (3m/6m/1y/2y/MAX)
- **Recente orders** en trading statistieken

### 4.3 Telegram-login beveiliging

**Geen Telegram Login Widget.** In plaats daarvan OTP via Telegram Bot:

```
1. Gebruiker voert email in op /login.html
2. POST /auth/request → control_api genereert 6-cijferige OTP
3. OTP opgeslagen in SQLite (otp_codes tabel), vervalt na 10 minuten
4. OTP verzonden via Telegram Bot API naar TG_CHAT_ID
5. Gebruiker voert code in op dashboard
6. POST /auth/verify → control_api valideert code
7. Bij succes: session token (hex 64 chars), 24 uur geldig
8. Token opgeslagen in browser localStorage als oc_token + oc_expires
9. Dashboard checkt token geldigheid bij laden; redirect naar login bij verlopen
```

### 4.4 Gebruikersacties

Het dashboard is **alleen-lezen**. Geen order placement, geen trading controls.

| Actie | Beschikbaar? |
|-------|-------------|
| Realtime data bekijken | Ja |
| Backtest uitvoeren | Ja (GET /backtest/historical) |
| Orders plaatsen | Nee |
| Trading stoppen/pauzeren | Nee (alleen via Telegram) |
| Proposals indienen | Nee (alleen via Telegram/API) |
| Coins goedkeuren | Nee (alleen via Telegram) |

---

## 5. Market Oracle

### 5.1 Architectuur

Geisoleerde container (`market_oracle_sandbox`) zonder API keys of exchange credentials. Heeft alleen toegang tot publieke data.

### 5.2 Endpoints

| Method | URL | Request | Response |
|--------|-----|---------|----------|
| POST | `/run_event` | `{"event": "US CPI hoger dan verwacht", "focus": "btc,eth,gold"}` | Analyse JSON |
| POST | `/run_url` | `{"url": "https://reuters.com/..."}` | Analyse JSON |
| GET | `/scan` | — | Volledige marktscan |
| GET | `/health` | — | `{"status": "ok"}` |

### 5.3 Databronnen

**RSS feeds:**
- Reuters Business (`feeds.reuters.com/reuters/businessNews`)
- NYT Business (`rss.nytimes.com/services/xml/rss/nyt/Business.xml`)
- CoinDesk (`coindesk.com/arc/outboundfeeds/rss/`)

**Yahoo Finance tickers:**
- Crypto: BTC-USD, ETH-USD
- Commodities: GC=F (goud), CL=F (olie)
- Indices: ^GSPC (S&P 500), DX-Y.NYB (Dollar Index), ^VIX

### 5.4 Analyse output

```json
{
  "analysis": {
    "short_term": {"outlook": "bearish", "confidence": 0.7},
    "medium_term": {"outlook": "neutral", "confidence": 0.5},
    "long_term": {"outlook": "bullish", "confidence": 0.6}
  },
  "key_factors": ["Fed rate hike verwacht", "BTC hash rate ATH"],
  "contrarian_risk": 0.3,
  "suggested_actions": ["PAUSE", "TIGHTEN_STOPLOSS"],
  "timestamp": "2026-03-05T20:00:00Z"
}
```

**Sentiment scoring:** Gebruikt BEARISH_WORDS en BULLISH_WORDS lijsten. Telt voorkomens in headlines. Genereert gewogen score per periode.

### 5.5 Integratie met control_api

Oracle output wordt via de `macro_context_oracle` OpenClaw skill naar control_api gestuurd:

```bash
curl -s -X POST http://control_api:8080/context/macro \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -d '<oracle JSON output>'
```

**Regels:**
- Oracle output is **adviserend** — nooit direct uitvoeren
- Elke actie moet via de **gatekeeper skill** als voorstel worden ingediend
- Alleen PAUSE/NO_BUY/EXIT_ONLY mogen automatisch (flash-crash policy)
- Macro context mag **NOOIT** leiden tot ALLOW_LIVE=true

### 5.6 Resource limieten

```yaml
deploy:
  resources:
    limits:
      cpus: "0.5"
      memory: 256M
```

---

## 6. Omgevingsvariabelen

### 6.1 apex.env

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `TRADING_MODE` | Ja | Moet `demo` zijn. Andere waarden blokkeren opstart |
| `EXECUTOR_MODE` | Ja | Moet `blofin_demo` zijn |
| `ALLOW_LIVE` | Ja | Moet `false` zijn |
| `BLOFIN_API_KEY` | Ja | BloFin demo API key |
| `BLOFIN_API_SECRET` | Ja | BloFin demo API secret |
| `BLOFIN_API_PASSPHRASE` | Ja | BloFin demo API passphrase |
| `SYMBOL` | Nee | Standaard trading symbol |
| `FEE_BPS` | Nee | Fee in basis points |
| `SLIPPAGE_BPS` | Nee | Slippage in basis points |
| `CRYPTOPANIC_TOKEN` | Nee | CryptoPanic API token voor nieuws |
| `PRE_CRASH_BUY_BLOCK` | Nee | Crash score drempel (default 60) |
| `EXCHANGE_INTEL_ENABLED` | Nee | Multi-exchange consensus (default true) |
| `KIMI_API_KEY` | Ja | Kimi AI API key voor coin selectie |
| `KIMI_BASE_URL` | Ja | Kimi API base URL |
| `KIMI_MODEL` | Nee | Kimi model (default moonshotai/kimi-k2.5) |
| `CONTROL_API_URL` | Ja | `http://control_api:8080` |
| `CONTROL_API_TOKEN` | Ja | Gedeeld token met control_api |
| `TG_BOT_TOKEN_COORDINATOR` | Ja | Telegram bot token voor meldingen |
| `TG_CHAT_ID` | Ja | Telegram chat ID voor meldingen |

### 6.2 control_api.env

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `CONTROL_API_TOKEN` | Ja | Statische API key voor authenticatie |
| `MIN_PROFIT_FACTOR` | Nee | Minimale profit factor voor backtests |
| `MAX_DRAWDOWN_PCT` | Nee | Maximale drawdown percentage |
| `MIN_TRADES` | Nee | Minimaal aantal trades voor statistieken |
| `MAX_APPLIES_PER_DAY` | Nee | Max proposal applies per dag (default 3) |
| `AUTO_ROLLBACK` | Nee | Automatisch terugdraaien bij slechte resultaten |

### 6.3 openclaw_gateway.env

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `OPENCLAW_GATEWAY_TOKEN` | Ja | Auth token voor OpenClaw gateway |
| `ANTHROPIC_API_KEY` | Ja | Claude API key |
| `TELEGRAM_BOT_TOKEN` | Ja | Nieuw bot token (aparte bot van coordinator/discuss) |
| `TG_ALLOWED_USER_ID` | Ja | Frans's Telegram user ID (7381250590) |
| `CONTROL_API_URL` | Ja | `http://control_api:8080` |
| `CONTROL_API_TOKEN` | Ja | Gedeeld token met control_api |

### 6.4 openclaw.env (legacy agent)

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `OPENAI_API_KEY` | Nee | OpenAI API key (fallback) |
| `ANTHROPIC_API_KEY` | Ja | Claude API key |
| `KIMI_API_KEY` | Ja | Kimi AI key |
| `KIMI_BASE_URL` | Ja | Kimi API base URL |
| `KIMI_MODEL` | Nee | Kimi model |
| `CONTROL_API_URL` | Ja | `http://control_api:8080` |
| `CONTROL_API_TOKEN` | Ja | Gedeeld token |
| `LEARN_INTERVAL` | Nee | Leer-agent interval |
| `BACKTEST_INTERVAL` | Nee | Backtest interval |
| `MIN_SIGNALS` | Nee | Minimaal signalen voor analyse |
| `MAX_APPLIES_PER_DAY` | Nee | Max applies |
| `TG_BOT_TOKEN_COORDINATOR` | Ja | Telegram bot token |
| `TG_CHAT_ID` | Ja | Telegram chat ID |

### 6.5 telegram_coordinator.env

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Ja | Bot token voor coordinator |
| `TELEGRAM_CHAT_ID` | Ja | Target chat ID |
| `CONTROL_API_URL` | Ja | `http://control_api:8080` |
| `CONTROL_API_TOKEN` | Ja | Gedeeld token |
| `BOT_NAME` | Nee | Weergavenaam |

### 6.6 telegram_discuss.env

| Variabele | Verplicht | Beschrijving |
|-----------|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Ja | Bot token voor discuss bot |
| `TELEGRAM_ALLOWED_USERS` | Ja | Komma-gescheiden lijst van toegestane user IDs |
| `CONTROL_API_URL` | Ja | `http://control_api:8080` |
| `CONTROL_API_TOKEN` | Ja | Gedeeld token |
| `BOT_NAME` | Nee | Weergavenaam |
| `AUTO_MODE_DEFAULT` | Nee | Default auto-modus |
| `KIMI_API_KEY` | Ja | Voor AI-antwoorden |
| `KIMI_BASE_URL` | Ja | Kimi API URL |
| `KIMI_MODEL` | Nee | Kimi model |

### 6.7 Secrets overzicht (namen, geen waarden)

| Bestand | Secrets |
|---------|---------|
| `secrets/apex.env` | BLOFIN_API_KEY, BLOFIN_API_SECRET, BLOFIN_API_PASSPHRASE, KIMI_API_KEY, CONTROL_API_TOKEN, TG_BOT_TOKEN_COORDINATOR, CRYPTOPANIC_TOKEN |
| `secrets/control_api.env` | CONTROL_API_TOKEN |
| `secrets/openclaw.env` | ANTHROPIC_API_KEY, OPENAI_API_KEY, KIMI_API_KEY, CONTROL_API_TOKEN, TG_BOT_TOKEN_COORDINATOR |
| `secrets/openclaw_gateway.env` | OPENCLAW_GATEWAY_TOKEN, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, CONTROL_API_TOKEN |
| `secrets/telegram_coordinator.env` | TELEGRAM_BOT_TOKEN, CONTROL_API_TOKEN |
| `secrets/telegram_discuss.env` | TELEGRAM_BOT_TOKEN, KIMI_API_KEY, CONTROL_API_TOKEN |

Alle `.env` bestanden staan in `.gitignore`. Alleen `.env.example` bestanden worden gecommit.

---

## 7. Beveiliging

### 7.1 Poorten

| Poort | Binding | Toegang | Service |
|-------|---------|---------|---------|
| 3000 | 0.0.0.0 | **PUBLIEK** | Dashboard (nginx) |
| 8080 | 0.0.0.0 | **PUBLIEK** | control_api |
| 18789 | 127.0.0.1 | Alleen localhost | openclaw_gateway |
| 8090 | 127.0.0.1 | Alleen localhost | openclaw_runtime |
| 8095 | 127.0.0.1 | Alleen localhost | market_oracle_sandbox |

**Aanbeveling:** Poort 8080 zou idealiter ook op 127.0.0.1 moeten staan met een reverse proxy (nginx) ervoor. Huidige configuratie exposeert de API direct.

### 7.2 Authenticatie per service

| Service | Mechanisme |
|---------|-----------|
| control_api | `X-API-KEY` header (statische token) of session token (24h, via OTP) |
| openclaw_gateway | `OPENCLAW_GATEWAY_TOKEN` voor gateway API, Telegram allowlist voor gebruikers |
| dashboard | OTP via Telegram → session token in localStorage |
| apex_engine | Geen directe API, communiceert via gedeelde bestanden |
| market_oracle_sandbox | Geen authenticatie (alleen intern bereikbaar) |
| tg_coordinator_bot | Geen eigen auth, gebruikt CONTROL_API_TOKEN naar control_api |
| tg_discuss_bot | TELEGRAM_ALLOWED_USERS whitelist + CONTROL_API_TOKEN |

### 7.3 Telegram allowlists

| Bot | Allowlist |
|-----|----------|
| openclaw_gateway | `allowFrom: [7381250590]` in openclaw.json + dmPolicy: "allowlist" |
| tg_discuss_bot | `TELEGRAM_ALLOWED_USERS` env var (user IDs) |
| tg_coordinator_bot | Alleen output, geen input verwerking |

### 7.4 Netwerk isolatie

```
trade_net (geisoleerd):
  - apex_engine (geen poort exposed)
  - control_api (bridge naar agent_net)

agent_net:
  - control_api
  - Alle andere services

market_oracle_sandbox:
  - Alleen agent_net
  - Geen secrets volume gemount
  - Resource limits: 0.5 CPU, 256MB RAM
  - Geen exchange keys, geen AI keys
```

### 7.5 Wat NOOIT toegestaan is

1. **ALLOW_LIVE=true** — Geblokkeerd op 3 niveaus:
   - apex_engine: `RuntimeError` bij opstart als `ALLOW_LIVE` niet `false`
   - control_api: HTTP 403 bij elke proposal die `ALLOW_LIVE` of `allow_live` in payload heeft
   - control_api: `/status` rapporteert altijd `"allow_live": false`

2. **Directe exchange calls vanuit AI agents** — Agents communiceren alleen via control_api

3. **Market Oracle directe trade uitvoering** — Oracle output is adviserend, moet via gatekeeper skill als voorstel

4. **Meer dan 3 applies per dag** — Hardcoded limiet, HTTP 429 bij overschrijding

5. **Parameters buiten PARAM_BOUNDS** — Worden automatisch geclamped

6. **Marketplace skills in OpenClaw** — Alleen lokale skills uit `/workspace/skills/`

### 7.6 Versie pinning

OpenClaw gateway submodule is gepind op `v2026.3.2` (bevat ClawJacked fix v2026.2.25+). Dockerfile controleert versie bij build:

```dockerfile
RUN node -e "const v=require('./package.json').version; \
  if(v < '2026.2.25') { console.error('FATAL: version '+v); process.exit(1); }"
```

---

## 8. Hoe te testen

### 8.1 Verificatie dat alles draait

```bash
# Alle containers status
docker compose ps

# Health checks
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
curl -s http://127.0.0.1:18789/health | python3 -m json.tool
curl -s http://127.0.0.1:8095/health | python3 -m json.tool

# Dashboard bereikbaar
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/login.html
# Verwacht: 200

# Volledige platform status
curl -s http://127.0.0.1:8080/status \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool

# Apex engine logs
docker compose logs --tail=50 apex_engine

# Control API logs
docker compose logs --tail=50 control_api
```

### 8.2 Unit tests (policy engine)

```bash
docker compose exec control_api python -m pytest /app/tests/ -v
```

Test coverage:
- `TestParamBounds`: validatie, clamping, non-numeriek, meerdere violations
- `TestAppliesLimit`: binnen limiet, op limiet (429), reset bij nieuwe dag
- `TestFlashCrashActions`: PAUSE/NO_BUY/EXIT_ONLY zijn auto, PARAM_CHANGE/RESUME niet
- `TestProposalTypes`: alle verwachte types aanwezig
- `TestAllowLiveBlocked`: ALLOW_LIVE niet in PARAM_BOUNDS

### 8.3 Backtest uitvoeren

**Via API:**
```bash
# Quick backtest BTC, 1h candles, 500 samples
curl -s "http://127.0.0.1:8080/backtest/BTCUSDT?interval=1h&limit=500" \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool

# Historische 6-maanden backtest
curl -s "http://127.0.0.1:8080/backtest/historical/BTCUSDT?interval=1h&months=6" \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool

# Async backtest starten
curl -s -X POST http://127.0.0.1:8080/backtest/run \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "ETHUSDT", "interval": "4h"}' | python3 -m json.tool
# Noteer job_id

# Resultaat ophalen
curl -s "http://127.0.0.1:8080/backtest/result/<job_id>" \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool
```

**Via Telegram:**
```
/backtest BTCUSDT 4h
```

**Via Dashboard:**
Selecteer coin en periode in de backtest sectie. Resultaten worden automatisch getoond.

### 8.4 Proposal indienen en bevestigen

**Stap 1: Proposal indienen**
```bash
curl -s -X POST http://127.0.0.1:8080/proposals \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "PARAM_CHANGE",
    "payload": {"rsi_buy_threshold": 32, "stoploss_pct": 3.0},
    "reason": "Win rate te laag, conservatiever",
    "requested_by": "test",
    "requires_confirm": true
  }' | python3 -m json.tool
```

**Verwachte response:**
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

Er wordt een Telegram bericht gestuurd met de OTP code.

**Stap 2: Pending proposals bekijken**
```bash
curl -s "http://127.0.0.1:8080/proposals/v2?state=pending" \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool
```

**Stap 3: Bevestigen met OTP**
```bash
curl -s -X POST http://127.0.0.1:8080/proposals/a1b2c3d4/confirm \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -H "X-OTP: 123456" | python3 -m json.tool
```

**Verwachte response:**
```json
{
  "ok": true,
  "proposal_id": "a1b2c3d4",
  "status": "confirmed",
  "applied": true,
  "applies_today": 1
}
```

**Flash-crash auto-apply (zonder bevestiging):**
```bash
curl -s -X POST http://127.0.0.1:8080/proposals \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "PAUSE",
    "payload": {"minutes": 30},
    "reason": "Flash crash gedetecteerd",
    "requested_by": "apex_engine",
    "requires_confirm": false
  }' | python3 -m json.tool
```

Response heeft `"status": "auto_applied"` — onmiddellijk uitgevoerd, geen OTP nodig.

### 8.5 Market Oracle testen

```bash
# Health check
curl -s http://127.0.0.1:8095/health | python3 -m json.tool

# Volledige marktscan
curl -s http://127.0.0.1:8095/scan | python3 -m json.tool

# Event analyse
curl -s -X POST http://127.0.0.1:8095/run_event \
  -H "Content-Type: application/json" \
  -d '{"event": "Fed verhoogt rente met 50 bps", "focus": "btc,eth,sp500"}' \
  | python3 -m json.tool

# Macro context updaten in control_api
curl -s -X POST http://127.0.0.1:8080/context/macro \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"analysis": {"short_term": {"outlook": "bearish", "confidence": 0.7}}, "key_factors": ["Fed rate hike"], "suggested_actions": ["PAUSE"], "timestamp": "2026-03-05T20:00:00Z"}' \
  | python3 -m json.tool

# Macro context ophalen
curl -s http://127.0.0.1:8080/context/macro \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool
```

### 8.6 Trading controls testen

```bash
# Pauzeer trading voor 30 minuten
curl -s -X POST http://127.0.0.1:8080/trading/pause \
  -H "X-API-KEY: $CONTROL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"minutes": 30, "reason": "Test pause"}' | python3 -m json.tool

# Check status
curl -s http://127.0.0.1:8080/trading/status \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool

# Resume
curl -s -X POST http://127.0.0.1:8080/trading/resume \
  -H "X-API-KEY: $CONTROL_API_TOKEN" | python3 -m json.tool
```

### 8.7 OpenClaw Gateway testen

```bash
# Health check (moet valid JSON retourneren)
curl -s http://127.0.0.1:18789/health | python3 -m json.tool

# Skills lijst (vanuit container)
docker compose exec openclaw_gateway node openclaw.mjs skills list

# Logs bekijken
docker compose logs --tail=50 openclaw_gateway
```

Test de Telegram interactie door een DM te sturen naar de OpenClaw bot. Alleen user ID 7381250590 wordt geaccepteerd.
