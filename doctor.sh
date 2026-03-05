#!/usr/bin/env bash
# doctor.sh — Diagnose OpenClaw Apex platform health
set -euo pipefail

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "${GRN}[OK]${NC}  $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; ERRORS=$((ERRORS+1)); }
warn() { echo -e "${YLW}[WARN]${NC} $1"; }

ERRORS=0

echo "=== OpenClaw Apex — Doctor ==="
echo ""

# ── Docker ────────────────────────────────────────────────────────────────────
echo "--- Docker ---"
if command -v docker >/dev/null 2>&1; then
  pass "Docker gevonden: $(docker --version)"
else
  fail "Docker niet gevonden"
fi

if command -v docker compose >/dev/null 2>&1 || docker compose version >/dev/null 2>&1; then
  pass "Docker Compose beschikbaar"
else
  fail "Docker Compose niet gevonden"
fi
echo ""

# ── Containers ────────────────────────────────────────────────────────────────
echo "--- Containers ---"
SERVICES=(apex_engine control_api openclaw openclaw_runtime dashboard tg_coordinator_bot tg_discuss_bot)
for svc in "${SERVICES[@]}"; do
  STATUS=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        if '${svc}' in d.get('Service','') or '${svc}' in d.get('Name',''):
            print(d.get('State','unknown'))
            break
    except: pass
" 2>/dev/null || echo "unknown")
  if [[ "$STATUS" == "running" ]]; then
    pass "$svc: running"
  elif [[ "$STATUS" == "unknown" ]]; then
    warn "$svc: niet actief of niet gestart"
  else
    fail "$svc: $STATUS"
  fi
done
echo ""

# ── API endpoints ─────────────────────────────────────────────────────────────
echo "--- API Health Checks ---"
check_http() {
  local url="$1"
  local label="$2"
  local body
  body=$(curl -sf --max-time 5 "$url" 2>/dev/null)
  if [[ $? -ne 0 ]]; then
    fail "$label: niet bereikbaar ($url)"
  elif echo "$body" | grep -q '"status"'; then
    pass "$label: bereikbaar + JSON ok ($url)"
  elif echo "$body" | grep -qi '<html'; then
    warn "$label: bereikbaar maar stuurt HTML i.p.v. JSON ($url)"
  else
    pass "$label: bereikbaar ($url)"
  fi
}

check_http "http://127.0.0.1:8080/health" "Control API"
check_http "http://127.0.0.1:8090/health" "OpenClaw Runtime"
check_http "http://127.0.0.1:18789/health" "OpenClaw Gateway"
check_http "http://127.0.0.1:3000/"       "Dashboard"
echo ""

# ── Secrets ───────────────────────────────────────────────────────────────────
echo "--- Secrets ---"
SECRETS_DIR="./secrets"
check_secret() {
  local file="$1"
  local key="$2"
  if [[ -f "$SECRETS_DIR/$file" ]] && grep -q "^${key}=.\+" "$SECRETS_DIR/$file" 2>/dev/null; then
    pass "$file → $key: ingevuld"
  else
    fail "$file → $key: LEEG of bestand ontbreekt"
  fi
}

check_secret "apex.env"        "BLOFIN_API_KEY"
check_secret "apex.env"        "KIMI_API_KEY"
check_secret "apex.env"        "CONTROL_API_TOKEN"
check_secret "openclaw.env"    "KIMI_API_KEY"
check_secret "openclaw.env"    "ANTHROPIC_API_KEY"
check_secret "openclaw.env"    "TG_BOT_TOKEN_COORDINATOR"
echo ""

# ── Submodule ─────────────────────────────────────────────────────────────────
echo "--- Git submodule ---"
if [[ -d "openclaw_framework/.git" ]] || [[ -f "openclaw_framework/.git" ]]; then
  pass "openclaw_framework submodule aanwezig"
else
  warn "openclaw_framework submodule niet geïnitialiseerd (run: git submodule update --init)"
fi
echo ""

# ── Samenvatting ──────────────────────────────────────────────────────────────
echo "=== Resultaat ==="
if [[ $ERRORS -eq 0 ]]; then
  echo -e "${GRN}Alles OK — platform klaar voor gebruik.${NC}"
else
  echo -e "${RED}$ERRORS probleem(en) gevonden. Los de FAIL-items op.${NC}"
  exit 1
fi
