# Installation Guide — OpenClaw Apex v2

This guide takes you from zero to a fully running platform: containers up, historical data loaded, Jojo1 (AI operator) active via Telegram, and the dashboard accessible.

---

## Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 40 GB |
| OS | Ubuntu 22.04 | Ubuntu 22.04 / 24.04 |
| Docker | 24.x | latest |
| Docker Compose | v2.x | latest |

> The platform is designed to run on a VPS. All services run inside Docker — no local Python or Node.js installation needed.

> **OpenClaw framework:** The AI operator (Jojo1) uses the open-source [openclaw/openclaw](https://github.com/openclaw/openclaw) TypeScript framework. It is automatically downloaded from GitHub during `docker compose build`. You do not need to clone it separately.

---

## Step 1 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

---

## Step 2 — Clone the repository

```bash
git clone https://github.com/frans1979valk/openclaw-apex-v2.git
cd openclaw-apex-v2
```

---

## Step 3 — Create secrets

All API keys and tokens go in `secrets/*.env`. These files are **never committed to git**.

```bash
# Copy all example files
cp secrets/apex.env.example secrets/apex.env
cp secrets/control_api.env.example secrets/control_api.env
cp secrets/openclaw_gateway.env.example secrets/openclaw_gateway.env
cp secrets/telegram_coordinator.env.example secrets/telegram_coordinator.env
cp secrets/telegram_discuss.env.example secrets/telegram_discuss.env
cp secrets/postgres.env.example secrets/postgres.env
```

### 3a. `secrets/postgres.env`

```env
POSTGRES_USER=apex
POSTGRES_PASSWORD=choose-a-strong-password
POSTGRES_DB=apex
DATABASE_URL=postgresql://apex:choose-a-strong-password@postgres:5432/apex
```

### 3b. `secrets/control_api.env`

```env
CONTROL_API_TOKEN=choose-a-strong-random-token
TG_BOT_TOKEN=<your Telegram bot token>
TG_CHAT_ID=<your Telegram chat ID>
DATABASE_URL=postgresql://apex:your-password@postgres:5432/apex
```

> To get `TG_CHAT_ID`: send a message to your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in your browser.

### 3c. `secrets/apex.env` — BloFin keys

**For paper trading (demo mode):**
```env
BLOFIN_API_KEY=<your BloFin demo API key>
BLOFIN_API_SECRET=<your BloFin demo API secret>
BLOFIN_PASSPHRASE=<your BloFin demo passphrase>
ALLOW_LIVE=false
```

**For live trading:**
```env
BLOFIN_API_KEY=<your BloFin LIVE API key>
BLOFIN_API_SECRET=<your BloFin LIVE API secret>
BLOFIN_PASSPHRASE=<your BloFin LIVE passphrase>
ALLOW_LIVE=true
```

> Get BloFin API keys at: [blofin.com](https://blofin.com) → Account → API Management

### 3d. `secrets/openclaw_gateway.env` — Jojo1 (AI operator)

```env
OPENCLAW_GATEWAY_TOKEN=<generate: openssl rand -hex 32>
ANTHROPIC_API_KEY=<your Anthropic API key>
TELEGRAM_BOT_TOKEN=<your Jojo1 Telegram bot token>
TG_ALLOWED_USER_ID=<your Telegram user ID>
CONTROL_API_URL=http://control_api:8080
CONTROL_API_TOKEN=<same token as in control_api.env>
```

> Get an Anthropic API key at: [console.anthropic.com](https://console.anthropic.com)

> To get your Telegram user ID: message [@userinfobot](https://t.me/userinfobot) on Telegram.

---

## Step 4 — Build the OpenClaw framework (Jojo1)

The AI operator (Jojo1) is built on the open-source [openclaw/openclaw](https://github.com/openclaw/openclaw) TypeScript framework. During the build, Docker clones and compiles this framework automatically.

> **Note:** The build requires an internet connection and takes **3–8 minutes** on the first run (Node.js dependencies + TypeScript compile).

```bash
# Build the gateway container first (downloads openclaw from GitHub)
docker compose build openclaw_gateway

# Then build and start everything else
docker compose up -d

# Check that all containers are running
docker compose ps
```

All containers should show status `Up`.

> If the build fails with pnpm or Node.js errors, retry with:
> ```bash
> docker compose build --no-cache openclaw_gateway
> ```

---

## Step 5 — Initialize the database

The PostgreSQL schema is created automatically on first start via `db/init.sql`. Verify:

```bash
docker compose exec postgres psql -U apex -d apex -c "\dt"
```

You should see a list of tables including `ohlcv_data`, `indicators_data`, `historical_context`, `testbot_trades`, etc.

---

## Step 6 — Load historical data

This is the most important step. The platform needs 4 years of OHLCV candle data to calculate indicators and run the P1 setup scoring system.

### 6a. Start the import (runs in background, takes 20–60 minutes)

```bash
curl -X POST http://localhost:8099/import \
  -H "Content-Type: application/json" \
  -d '{"months": 48, "intervals": ["1h", "4h"]}'
```

Response: `{"ok": true, "message": "Import started for 17 coins"}`

### 6b. Monitor import progress

```bash
# Check indicator_engine logs
docker compose logs -f indicator_engine

# Or check coverage (how many candles are loaded per coin)
curl http://localhost:8099/coverage | python3 -m json.tool
```

### 6c. Verify data is loaded

```bash
# Should show ~35,000+ rows per coin
docker compose exec postgres psql -U apex -d apex \
  -c "SELECT symbol, COUNT(*) FROM ohlcv_data WHERE interval='1h' GROUP BY symbol ORDER BY symbol;"
```

---

## Step 7 — Run the historical backtest

After OHLCV data is loaded, run the backtest to populate `historical_context`. This is needed for the P1 setup scoring (STERK/TOESTAAN verdicts).

```bash
# Trigger backtest via control_api
curl -X POST http://localhost:8080/backtest/run \
  -H "X-API-KEY: your-control-api-token" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "interval": "1h"}'
```

Repeat for each coin, or use the bulk endpoint if available. Check progress:

```bash
docker compose exec postgres psql -U apex -d apex \
  -c "SELECT symbol, COUNT(*) FROM historical_context GROUP BY symbol ORDER BY symbol;"
```

---

## Step 8 — Set up Jojo1 (AI operator via Telegram)

### 8a. Create a Telegram bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot`
3. Choose a name and username (must end with `_bot`)
4. Copy the token → paste into `secrets/openclaw_gateway.env` as `TELEGRAM_BOT_TOKEN`

### 8b. Restart the gateway

```bash
docker compose restart openclaw_gateway

# Check it started correctly
docker compose logs openclaw_gateway | tail -20
```

### 8c. Pair with Telegram

1. Open Telegram and send a message to your new bot
2. The bot will respond and pair automatically
3. Test it:

```
status
```

Jojo1 should reply with current market status, crash score and active signals.

---

## Step 9 — Access the dashboard

The web dashboard runs on port 4000:

```
http://your-vps-ip:4000
```

### Login

1. Enter your email on the login page
2. You receive a 6-digit OTP code via Telegram
3. Enter the code → you are logged in

### Dashboard pages

| Page | URL | What you see |
|------|-----|-------------|
| Home | `/` | Navigation + status overview |
| Live Signals | `/live_signals.html` | Current RSI/MACD/ADX per coin, active signal, P1 verdict |
| Setup Intelligence | `/setup_intelligence.html` | Historical quality per (coin x signal type) |
| Chart | `/chart.html` | Candlestick chart + Setup Intel markers + bot trade markers |
| Bot Positions | `/bot_positions.html` | Open paper trades with live price + TP/SL progress |
| STERK Quality | `/sterk_quality.html` | Closed trades analysis, cumulative PnL chart |

---

## Step 10 — Start the paper trading testbot

The testbot opens paper trades automatically when a STERK signal is detected.

```bash
curl -X POST http://localhost:8080/testbot/start \
  -H "X-API-KEY: your-control-api-token"
```

Check status:

```bash
curl http://localhost:8080/testbot/status \
  -H "X-API-KEY: your-control-api-token" | python3 -m json.tool
```

---

## Verify everything is working

```bash
# All containers running?
docker compose ps

# API healthy?
curl http://localhost:8080/health

# Indicator engine healthy?
curl http://localhost:8099/health

# Data loaded?
curl http://localhost:8099/coverage | python3 -m json.tool

# Live signals working?
curl http://localhost:8080/live/signals \
  -H "X-API-KEY: your-control-api-token" | python3 -m json.tool
```

---

## Enabling HTTPS (optional but recommended)

For production, use a Cloudflare tunnel or Caddy reverse proxy:

### Option A: Cloudflare Tunnel (easiest)

```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared-linux-amd64.deb

# Create a tunnel (one-time)
cloudflared tunnel login
cloudflared tunnel create openclaw
cloudflared tunnel route dns openclaw yourdomain.com
cloudflared tunnel run --url http://localhost:4000 openclaw
```

### Option B: Caddy reverse proxy

```bash
apt install caddy

# /etc/caddy/Caddyfile
yourdomain.com {
    reverse_proxy localhost:4000
}

systemctl restart caddy
```

---

## Troubleshooting

**Container not starting:**
```bash
docker compose logs <service-name>
```

**Database connection error:**
```bash
# Check PostgreSQL is running
docker compose ps postgres

# Check DATABASE_URL in secrets matches postgres.env
cat secrets/postgres.env
cat secrets/control_api.env
```

**No data in Setup Intelligence:**
- Make sure Step 6 (OHLCV import) completed successfully
- Make sure Step 7 (backtest) ran for your coins
- Check: `docker compose logs indicator_engine | grep -i error`

**Jojo1 not responding in Telegram:**
```bash
docker compose logs openclaw_gateway | tail -30
# Check: correct TELEGRAM_BOT_TOKEN? TG_ALLOWED_USER_ID set?
```

**Dashboard shows no signals:**
- Indicators data must be loaded (Step 6)
- Check: `curl http://localhost:8099/indicators/BTCUSDT`

---

## Updating

```bash
git pull origin main
docker compose build
docker compose up -d
```

---

## Uninstall

```bash
docker compose down -v   # stops containers and removes volumes (including database!)
docker compose down      # stops containers only (keeps data)
```

> Use `down` (without `-v`) if you want to keep your historical data.
