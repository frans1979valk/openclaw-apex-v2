"""
OpenClaw - Autonome Trading Platform Beheerder
Leert van signal performance, past parameters aan, triggert backtests
"""
import os
import time
import json
import requests
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


CONTROL_API_URL = os.getenv("CONTROL_API_URL", "http://control_api:8080")
CONTROL_API_TOKEN = os.getenv("CONTROL_API_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN_COORDINATOR", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

LEARN_INTERVAL = int(os.getenv("LEARN_INTERVAL", "1800"))
BACKTEST_INTERVAL = int(os.getenv("BACKTEST_INTERVAL", "3600"))
MIN_SIGNALS = int(os.getenv("MIN_SIGNALS", "10"))
MAX_APPLIES_PER_DAY = int(os.getenv("MAX_APPLIES_PER_DAY", "3"))

PARAM_BOUNDS = {
    "rsi_buy_threshold": (20, 40),
    "rsi_sell_threshold": (60, 80),
    "stoploss_pct": (1.5, 6.0),
    "takeprofit_pct": (3.0, 12.0),
    "position_size_base": (1, 5),
}


def log(message: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")


def send_telegram(message: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        log(f"Telegram fout: {e}")


def api_headers() -> Dict[str, str]:
    return {"X-API-KEY": CONTROL_API_TOKEN}


def get_signal_performance(limit: int = 100) -> List[Dict]:
    try:
        r = requests.get(
            f"{CONTROL_API_URL}/signal-performance",
            headers=api_headers(),
            params={"limit": limit},
            timeout=15
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"Signal performance fout: {e}")
        return []


def analyze_with_kimi(performance_data: List[Dict]) -> Optional[Dict]:
    if not OPENAI_API_KEY:
        log("OpenAI API key ontbreekt — skip AI analyse")
        return None

    if len(performance_data) < MIN_SIGNALS:
        log(f"Te weinig signalen ({len(performance_data)}) — wacht tot {MIN_SIGNALS}")
        return None

    by_signal: Dict[str, List[float]] = {}
    for sig in performance_data:
        sig_type = sig.get("signal", "UNKNOWN")
        pnl_1h = sig.get("pnl_1h_pct")
        if pnl_1h is not None:
            by_signal.setdefault(sig_type, []).append(pnl_1h)

    summary = []
    for sig_type, pnls in by_signal.items():
        wins = [p for p in pnls if p > 0]
        win_rate = len(wins) / len(pnls) * 100 if pnls else 0
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0
        summary.append(f"{sig_type}: {len(pnls)} signalen, win_rate={win_rate:.1f}%, avg_pnl={avg_pnl:.2f}%")

    summary_text = "\n".join(summary)

    prompt = f"""Je bent een trading parameter optimizer voor het OpenClaw platform.
De afgelopen {len(performance_data)} signalen leverden deze resultaten op:

{summary_text}

Analyse de data en stel parameter-aanpassingen voor om de performance te verbeteren.
Houd rekening met de volgende grenzen:
{json.dumps(PARAM_BOUNDS, indent=2)}

Geef een JSON response met exact deze structuur:
{{
  "analysis": "korte analyse (max 100 woorden)",
  "recommendations": {{
    "rsi_buy_threshold": 30,
    "rsi_sell_threshold": 70,
    "stoploss_pct": 3.0,
    "takeprofit_pct": 5.0,
    "position_size_base": 2
  }},
  "reasoning": "waarom deze parameters (max 100 woorden)"
}}

Alleen JSON, geen extra tekst."""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Je bent een trading parameter optimizer. Antwoord alleen met JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()

        result = json.loads(content)
        log(f"Kimi AI analyse: {result.get('analysis', '')}")
        return result

    except Exception as e:
        log(f"Kimi AI fout: {e}")
        return None


def validate_params(params: Dict[str, Any]) -> Dict[str, Any]:
    validated = {}
    for key, value in params.items():
        if key in PARAM_BOUNDS:
            min_val, max_val = PARAM_BOUNDS[key]
            validated[key] = max(min_val, min(max_val, value))
        else:
            validated[key] = value
    return validated


def create_proposal(params: Dict, reason: str) -> Optional[int]:
    try:
        payload = {
            "agent": "OpenClaw",
            "params": params,
            "reason": reason
        }
        r = requests.post(
            f"{CONTROL_API_URL}/config/propose",
            headers=api_headers(),
            json=payload,
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        proposal_id = data.get("proposal_id")
        log(f"Proposal aangemaakt: #{proposal_id}")
        return proposal_id
    except Exception as e:
        log(f"Proposal fout: {e}")
        return None


def apply_proposal(proposal_id: int) -> bool:
    try:
        r = requests.post(
            f"{CONTROL_API_URL}/proposals/{proposal_id}/apply",
            headers=api_headers(),
            timeout=10
        )
        r.raise_for_status()
        log(f"Proposal #{proposal_id} toegepast")
        return True
    except Exception as e:
        log(f"Apply fout: {e}")
        return False


def get_state() -> Dict:
    try:
        r = requests.get(
            f"{CONTROL_API_URL}/state/latest",
            headers=api_headers(),
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log(f"State fout: {e}")
        return {}


def trigger_backtest(symbol: str, months: int = 1):
    try:
        log(f"Trigger backtest: {symbol} ({months} maanden)")
        r = requests.get(
            f"{CONTROL_API_URL}/backtest/historical/{symbol}",
            headers=api_headers(),
            params={"interval": "1h", "months": months},
            timeout=60
        )
        r.raise_for_status()
        data = r.json()
        signals = data.get("signals_found", 0)
        log(f"Backtest {symbol}: {signals} signalen gevonden")
        return data
    except Exception as e:
        log(f"Backtest fout {symbol}: {e}")
        return None


class ApplyLimiter:
    def __init__(self, max_per_day: int):
        self.max_per_day = max_per_day
        self.applies_today = 0
        self.last_reset = datetime.now(timezone.utc).date()

    def can_apply(self) -> bool:
        today = datetime.now(timezone.utc).date()
        if today > self.last_reset:
            self.applies_today = 0
            self.last_reset = today

        return self.applies_today < self.max_per_day

    def record_apply(self):
        self.applies_today += 1


def learning_loop(limiter: ApplyLimiter):
    log("=== Learning Loop Start ===")

    performance = get_signal_performance(limit=100)
    if not performance:
        log("Geen signal performance data — skip")
        return

    log(f"Signal performance data: {len(performance)} entries")

    ai_result = analyze_with_kimi(performance)
    if not ai_result:
        log("AI analyse mislukt — skip")
        return

    recommendations = ai_result.get("recommendations", {})
    validated = validate_params(recommendations)

    log(f"AI aanbevelingen: {validated}")

    proposal_id = create_proposal(
        validated,
        f"AI optimize: {ai_result.get('reasoning', 'geen reden')}"
    )

    if not proposal_id:
        log("Proposal aanmaken mislukt")
        return

    if not limiter.can_apply():
        log(f"Apply limiet bereikt ({limiter.max_per_day}/dag) — proposal #{proposal_id} wacht op goedkeuring")
        send_telegram(
            f"🤖 *OpenClaw Proposal #{proposal_id}*\n\n"
            f"Aanbevolen parameters:\n{json.dumps(validated, indent=2)}\n\n"
            f"Reden: {ai_result.get('reasoning', '')}\n\n"
            f"⚠️ Dagelijkse limiet bereikt — wacht op handmatige goedkeuring"
        )
        return

    if apply_proposal(proposal_id):
        limiter.record_apply()
        send_telegram(
            f"✅ *OpenClaw Proposal #{proposal_id} Toegepast*\n\n"
            f"Parameters bijgewerkt:\n{json.dumps(validated, indent=2)}\n\n"
            f"Reden: {ai_result.get('reasoning', '')}"
        )
    else:
        log(f"Proposal #{proposal_id} toepassen mislukt")


def backtest_loop():
    log("=== Backtest Loop Start ===")

    state = get_state()
    coins = state.get("coins", [])

    if not coins:
        log("Geen coins gevonden in state — skip backtest")
        return

    log(f"Trigger backtests voor {len(coins)} coins")

    for coin in coins:
        symbol = coin.get("symbol", "")
        if not symbol:
            continue

        result = trigger_backtest(symbol, months=1)
        if result:
            signals = result.get("signals_found", 0)
            overall_1h = result.get("overall_1h", {})
            win_rate = overall_1h.get("win_rate_pct", 0)
            avg_pnl = overall_1h.get("avg_pnl_pct", 0)

            log(f"{symbol}: {signals} signalen, win_rate={win_rate}%, avg_pnl={avg_pnl}%")

        time.sleep(2)


def main():
    log("🦅 OpenClaw Agent Start")
    send_telegram("🦅 *OpenClaw Agent Online*\n\nAutonome learning en backtest cycles actief.")

    limiter = ApplyLimiter(MAX_APPLIES_PER_DAY)
    last_learn = 0.0
    last_backtest = 0.0

    while True:
        now = time.time()

        if now - last_learn > LEARN_INTERVAL:
            try:
                learning_loop(limiter)
                last_learn = now
            except Exception as e:
                log(f"Learning loop error: {e}")

        if now - last_backtest > BACKTEST_INTERVAL:
            try:
                backtest_loop()
                last_backtest = now
            except Exception as e:
                log(f"Backtest loop error: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()
