"""
OpenClaw Autonome Agent — baas van het platform.
Learning loop: analyseert signaal-performance en past parameters aan via Kimi AI.
Backtest loop: triggert historische backtests voor bijgehouden coins.

Veiligheidslimieten (PARAM_BOUNDS) worden nooit overschreden.
MAX_APPLIES_PER_DAY voorkomt overmatige parameterwijzigingen.
"""
import os, json, time, logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests
from openai import OpenAI
from clawbot import ask_clawbot, clawbot_available

# ── Config ────────────────────────────────────────────────────────────────
CONTROL_API_URL   = os.getenv("CONTROL_API_URL",   "http://control_api:8080")
CONTROL_API_TOKEN = os.getenv("CONTROL_API_TOKEN", "")
KIMI_API_KEY      = os.getenv("KIMI_API_KEY",      "")
KIMI_BASE_URL     = os.getenv("KIMI_BASE_URL",     "https://integrate.api.nvidia.com/v1")
KIMI_MODEL        = os.getenv("KIMI_MODEL",        "moonshotai/kimi-k2.5")
TG_BOT_TOKEN      = os.getenv("TG_BOT_TOKEN_COORDINATOR", "")
TG_CHAT_ID        = os.getenv("TG_CHAT_ID",        "")

LEARN_INTERVAL    = int(os.getenv("LEARN_INTERVAL",    "1800"))   # 30 min
BACKTEST_INTERVAL = int(os.getenv("BACKTEST_INTERVAL", "3600"))   # 60 min
DECISION_INTERVAL = int(os.getenv("DECISION_INTERVAL", "900"))    # 15 min
MIN_SIGNALS       = int(os.getenv("MIN_SIGNALS",       "10"))
MAX_APPLIES_PER_DAY = int(os.getenv("MAX_APPLIES_PER_DAY", "3"))

# Absolute grenzen — OpenClaw mag hier NOOIT buiten
PARAM_BOUNDS = {
    "rsi_buy_threshold":  (20,  40),
    "rsi_sell_threshold": (60,  80),
    "stoploss_pct":       (1.5, 6.0),
    "takeprofit_pct":     (3.0, 12.0),
    "position_size_base": (1,   5),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [openclaw] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("openclaw")


# ── Helpers ───────────────────────────────────────────────────────────────

def _api_headers() -> Dict[str, str]:
    return {"X-API-KEY": CONTROL_API_TOKEN, "Content-Type": "application/json"}


def _api_get(path: str, params: Optional[Dict] = None) -> Optional[dict]:
    try:
        r = requests.get(f"{CONTROL_API_URL}{path}", headers=_api_headers(),
                         params=params, timeout=10)
        if r.ok:
            return r.json()
        log.warning(f"GET {path} → {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log.error(f"GET {path} fout: {e}")
    return None


def _api_post(path: str, payload: dict) -> Optional[dict]:
    try:
        r = requests.post(f"{CONTROL_API_URL}{path}", headers=_api_headers(),
                          json=payload, timeout=10)
        if r.ok:
            return r.json()
        log.warning(f"POST {path} → {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log.error(f"POST {path} fout: {e}")
    return None


def _send_telegram(msg: str) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception as e:
        log.warning(f"Telegram fout: {e}")


def _ask_kimi(system: str, user: str, max_tokens: int = 800) -> str:
    if not KIMI_API_KEY:
        return "{}"
    try:
        client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
        resp   = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"Kimi fout: {e}")
        return "{}"


def _parse_json(text: str) -> dict:
    try:
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return {}


def _clamp_params(params: dict) -> dict:
    """Dwing alle parameters binnen veilige grenzen."""
    clamped = {}
    for k, v in params.items():
        if k in PARAM_BOUNDS:
            lo, hi     = PARAM_BOUNDS[k]
            clamped[k] = max(lo, min(hi, float(v)))
        else:
            clamped[k] = v
    return clamped


# ── Dagelijkse teller ─────────────────────────────────────────────────────
_applies_today: int = 0
_applies_date:  str = ""


def _can_apply() -> bool:
    global _applies_today, _applies_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _applies_date:
        _applies_today = 0
        _applies_date  = today
    return _applies_today < MAX_APPLIES_PER_DAY


def _record_apply() -> None:
    global _applies_today
    _applies_today += 1


# ── Trading halt state ────────────────────────────────────────────────────

def _get_trading_status() -> dict:
    result = _api_get("/trading/status")
    return result or {"halted": False, "paused_until": None}


def _is_trading_halted() -> bool:
    status = _get_trading_status()
    if status.get("halted"):
        return True
    paused_until = status.get("paused_until")
    if paused_until:
        try:
            until = datetime.fromisoformat(paused_until)
            if datetime.now(timezone.utc) < until:
                return True
        except Exception:
            pass
    return False


# ── ask_user_with_countdown ────────────────────────────────────────────────

# Urgentie → wachttijd in seconden
URGENCY_TIMEOUT = {
    "LOW":      120,   # 2 minuten
    "MEDIUM":    60,   # 1 minuut
    "HIGH":      30,   # 30 seconden
    "CRITICAL":  15,   # 15 seconden
}

# Token voor pending question — discuss_bot schrijft antwoord hierop
_pending_question_id: Optional[str] = None


def ask_user_with_countdown(
    question: str,
    urgentie: str = "MEDIUM",
    default_actie: str = "AFWACHTEN",
    coin: str = "",
) -> str:
    """
    Stuur een vraag via Telegram met countdown en wacht op antwoord.

    De discuss_bot leest /ok, /stop, /skip commando's en slaat ze op via
    de control_api (/trading/answer). Wij pollen die endpoint totdat de
    timeout verlopen is.

    Args:
        question:      Vraag tekst
        urgentie:      LOW | MEDIUM | HIGH | CRITICAL
        default_actie: Actie als gebruiker niet reageert
        coin:          Coin waarover de vraag gaat

    Returns:
        Antwoord string: "ok" | "stop" | "skip" | default_actie (timeout)
    """
    global _pending_question_id

    timeout = URGENCY_TIMEOUT.get(urgentie, 60)
    q_id = f"q_{int(time.time())}"
    _pending_question_id = q_id

    urgency_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(urgentie, "⚪")

    # Stuur vraag naar Telegram
    msg = (
        f"{urgency_emoji} *OpenClaw vraagt jou* [{urgentie}]\n\n"
        f"{question}\n"
        + (f"📌 Coin: `{coin}`\n" if coin else "")
        + f"\n⏳ Timeout: {timeout}s → standaard: *{default_actie}*\n\n"
        f"Reageer met:\n"
        f"  `/ok` — uitvoeren\n"
        f"  `/stop` — noodstop\n"
        f"  `/skip` — sla over\n"
        f"_(vraag-id: `{q_id}`)_"
    )
    _send_telegram(msg)
    log.info(f"ask_user_with_countdown: urgentie={urgentie}, timeout={timeout}s, q_id={q_id}")

    # Poll control_api voor antwoord
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = int(deadline - time.time())
        try:
            r = _api_get("/trading/answer", {"q_id": q_id})
            if r and r.get("antwoord"):
                antwoord = r["antwoord"].lower().strip()
                log.info(f"Gebruiker antwoordde: {antwoord} op vraag {q_id}")
                _pending_question_id = None
                return antwoord
        except Exception:
            pass
        time.sleep(5)

    _pending_question_id = None
    log.info(f"Countdown verlopen — standaard actie: {default_actie}")
    _send_telegram(f"⏰ Geen reactie ontvangen — OpenClaw voert standaard actie uit: *{default_actie}*")
    return default_actie.lower()


# ── Morning Briefing ──────────────────────────────────────────────────────

_briefing_sent_today: str = ""


def morning_briefing() -> None:
    """Stuur elke dag om 07:00 UTC een uitgebreide marktbriefing."""
    global _briefing_sent_today
    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    if _briefing_sent_today == today:
        return
    if now_utc.hour != 7:
        return

    _briefing_sent_today = today
    log.info("=== Morning briefing genereren ===")

    state  = _api_get("/state/latest") or {}
    perf   = _api_get("/signal-performance", {"limit": 100}) or []
    coins  = state.get("coins", [])

    # Statistieken berekenen
    closed = [r for r in perf if r.get("pnl_1h_pct") is not None]
    wins   = [r for r in closed if r["pnl_1h_pct"] > 0]
    win_rate = round(len(wins) / len(closed) * 100) if closed else 0
    avg_pnl  = round(sum(r["pnl_1h_pct"] for r in closed) / len(closed), 2) if closed else 0

    top_coins = sorted(coins, key=lambda c: c.get("change_pct", 0), reverse=True)[:3]
    coin_lines = "\n".join(
        f"  • {c['symbol']}: {c.get('signal','?')} | RSI {c.get('rsi',0):.0f} | "
        f"{'+' if (c.get('change_pct') or 0) >= 0 else ''}{c.get('change_pct', 0):.1f}%"
        for c in top_coins
    )

    prompt_user = (
        f"Vandaag ({today}) marktoverzicht:\n"
        f"Win-rate gisteren: {win_rate}% ({len(wins)}/{len(closed)} trades)\n"
        f"Gem. P&L: {avg_pnl:+.2f}%\n"
        f"Top coins gevolgd:\n{coin_lines}\n\n"
        "Geef een korte marktbriefing (max 3 zinnen) + 1 concreet handeladvies voor vandaag."
    )

    analyse = _ask_kimi(
        system="Je bent een ervaren crypto trader die elke ochtend een briefing geeft. Wees concreet en beknopt.",
        user=prompt_user,
        max_tokens=300,
    )

    msg = (
        f"🌅 *OpenClaw Morning Briefing — {today}*\n\n"
        f"📊 Gisteren: win-rate {win_rate}% | gem. P&L {avg_pnl:+.2f}%\n"
        f"🎯 Signalen geëvalueerd: {len(closed)}\n\n"
        f"🤖 *AI Analyse:*\n{analyse}\n\n"
        f"📈 *Gevolgde coins:*\n{coin_lines}"
    )
    _send_telegram(msg)
    log.info("Morning briefing verstuurd.")


# ── Autonome Beslissingsengine ─────────────────────────────────────────────

_auto_decision_count_today: int = 0
_auto_decision_date: str = ""
MAX_AUTO_DECISIONS_PER_DAY = int(os.getenv("MAX_AUTO_DECISIONS_PER_DAY", "5"))


def _reset_daily_decisions():
    global _auto_decision_count_today, _auto_decision_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _auto_decision_date:
        _auto_decision_count_today = 0
        _auto_decision_date = today


def autonomous_decision_loop() -> None:
    """
    Analyseert de huidige markt autonomisch en neemt beslissingen:
    1. Kimi K2.5 analyseert signalen → eerste laag
    2. ClawBot (Claude Sonnet) reviewt → strategische laag
    3. Hoog-urgente beslissingen vragen gebruiker via countdown
    """
    global _auto_decision_count_today
    _reset_daily_decisions()
    if _auto_decision_count_today >= MAX_AUTO_DECISIONS_PER_DAY:
        return

    # Check noodstop
    if _is_trading_halted():
        log.info("Trading gepauzeerd/gestopt — autonome engine wacht.")
        return

    log.info("=== Autonome beslissingsengine (Kimi + ClawBot) ===")
    state = _api_get("/state/latest") or {}
    coins = state.get("coins", [])
    if not coins:
        return

    # Filter actionable coins
    buy_signals  = [c for c in coins if c.get("signal") in ("PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM", "BUY")]
    danger_coins = [c for c in coins if c.get("danger")]

    if not buy_signals and not danger_coins:
        log.info("Geen actionable signalen — autonome engine slaat over.")
        return

    coin_summary = "\n".join(
        f"  {c['symbol']}: {c.get('signal','?')} | RSI {c.get('rsi',0) or 0:.0f} | "
        f"TF-confirm: {c.get('tf_confirm', '?')} | tf_bias: {c.get('tf_bias','?')}"
        for c in coins[:8]
    )

    # ── Stap 1: Kimi analyse ─────────────────────────────────────────────
    prompt = (
        f"Actuele markt:\n{coin_summary}\n\n"
        f"Danger coins: {[c['symbol'] for c in danger_coins]}\n"
        f"Buy signalen: {[c['symbol'] for c in buy_signals]}\n\n"
        "Geef JSON:\n"
        '{"actie": "AFWACHTEN|INZETTEN|VERMIJDEN|SHORT", "coin": "BTCUSDT", "reden": "...", '
        '"countdown_minuten": 15, "confidence_pct": 70}'
    )
    raw  = _ask_kimi(
        system="Je bent een autonome trading beslissingsengine. Analyseer de markt en geef een concreet advies.",
        user=prompt,
        max_tokens=400,
    )
    kimi_decision = _parse_json(raw)
    if not kimi_decision or "actie" not in kimi_decision:
        log.info("Autonome engine: geen bruikbaar antwoord van Kimi.")
        return

    log.info(f"Kimi beslissing: {kimi_decision.get('actie')} | {kimi_decision.get('coin')} | "
             f"confidence={kimi_decision.get('confidence_pct')}%")

    # ── Stap 2: ClawBot strategische review ─────────────────────────────
    live_perf = _api_get("/signal-performance", {"limit": 50}) or []
    closed    = [r for r in live_perf if r.get("pnl_1h_pct") is not None]
    wins      = [r for r in closed if r["pnl_1h_pct"] > 0]
    live_perf_summary = {
        "total_signals":   len(live_perf),
        "closed_signals":  len(closed),
        "win_rate_pct":    round(len(wins) / len(closed) * 100) if closed else 0,
        "avg_pnl_1h":      round(sum(r["pnl_1h_pct"] for r in closed) / len(closed), 2) if closed else 0,
    }

    # Bepaal situatie voor ClawBot context
    situation = "normal"
    if any(c.get("flash_crash") for c in coins):
        situation = "market_crash"
    elif len(buy_signals) >= 3 and any(c.get("signal") == "PERFECT_DAY" for c in buy_signals):
        situation = "perfect_day_2x"
    elif live_perf_summary["win_rate_pct"] < 40 and live_perf_summary["closed_signals"] >= 10:
        situation = "win_rate_crash"

    final_decision = kimi_decision.copy()

    if clawbot_available():
        clawbot_result = ask_clawbot(
            kimi_output  = kimi_decision,
            db_context   = {},
            live_perf    = live_perf_summary,
            situation    = situation,
        )
        if clawbot_result and "beslissing" in clawbot_result:
            # ClawBot mapt "beslissing" → "actie" voor uniformiteit
            final_decision["actie"]        = clawbot_result["beslissing"]
            final_decision["reden"]        = clawbot_result.get("reden", kimi_decision.get("reden", ""))
            final_decision["confidence_pct"] = clawbot_result.get("confidence_pct",
                                                                   kimi_decision.get("confidence_pct", 0))
            final_decision["urgentie"]     = clawbot_result.get("urgentie", "LOW")
            final_decision["override_kimi"] = clawbot_result.get("override_kimi", False)
            log.info(f"ClawBot override: {clawbot_result.get('override_kimi')} | "
                     f"urgentie: {clawbot_result.get('urgentie')}")
    else:
        final_decision["urgentie"] = "LOW"

    actie      = final_decision.get("actie", "AFWACHTEN")
    coin       = final_decision.get("coin", "?")
    reden      = final_decision.get("reden", "")
    countdown  = final_decision.get("countdown_minuten", 0)
    confidence = final_decision.get("confidence_pct", 0)
    urgentie   = final_decision.get("urgentie", "LOW")

    _auto_decision_count_today += 1

    log.info(f"Finale beslissing: {actie} | {coin} | confidence={confidence}% | "
             f"urgentie={urgentie} | countdown={countdown}min")

    # ── Stap 3: Hoge urgentie → vraag gebruiker ──────────────────────────
    if urgentie in ("HIGH", "CRITICAL") and actie in ("INZETTEN", "SHORT"):
        vraag = (
            f"ClawBot adviseert *{actie}* op `{coin}` (confidence: {confidence}%).\n"
            f"💡 _{reden}_\n\nMag ik dit uitvoeren?"
        )
        antwoord = ask_user_with_countdown(
            question=vraag,
            urgentie=urgentie,
            default_actie="AFWACHTEN",
            coin=coin,
        )
        if antwoord == "stop":
            _send_telegram("🛑 Noodstop ontvangen — actie geannuleerd.")
            return
        elif antwoord not in ("ok",):
            _send_telegram(f"⏭️ Actie *{actie}* overgeslagen op gebruikersverzoek.")
            return

    emoji = {"INZETTEN": "🟢", "VERMIJDEN": "🔴", "AFWACHTEN": "🟡", "SHORT": "🩳"}.get(actie, "⚪")
    clawbot_tag = " _(ClawBot)_" if clawbot_available() else " _(Kimi)_"
    msg = (
        f"{emoji} *OpenClaw Autonome Beslissing*{clawbot_tag}\n\n"
        f"Actie: *{actie}*\n"
        f"Coin: `{coin}`\n"
        f"Confidence: {confidence}%\n"
        f"Urgentie: {urgentie}\n"
        f"💡 _{reden}_\n"
        + (f"\n⏳ Countdown: ~{countdown} minuten tot signaal" if countdown > 0 else "")
    )
    _send_telegram(msg)


# ── Learning loop ─────────────────────────────────────────────────────────

def learning_loop() -> None:
    """
    1. Haal signal_performance op
    2. Analyseer met Kimi welke signalen goed/slecht zijn
    3. Dien parameter-proposals in
    4. Pas ze toe (max MAX_APPLIES_PER_DAY per dag)
    5. Stuur Telegram bericht
    """
    log.info("=== Learning loop gestart ===")

    perf = _api_get("/signal-performance", {"limit": 200})
    if not perf or len(perf) < MIN_SIGNALS:
        log.info(f"Te weinig signalen ({len(perf) if perf else 0} < {MIN_SIGNALS}), sla over.")
        return

    # Statistieken per signaaltype
    stats: Dict[str, dict] = {}
    for row in perf:
        sig = row.get("signal", "?")
        if sig not in stats:
            stats[sig] = {"count": 0, "pnl_1h": [], "pnl_4h": []}
        stats[sig]["count"] += 1
        if row.get("pnl_1h_pct") is not None:
            stats[sig]["pnl_1h"].append(row["pnl_1h_pct"])
        if row.get("pnl_4h_pct") is not None:
            stats[sig]["pnl_4h"].append(row["pnl_4h_pct"])

    summary_lines = []
    for sig, s in stats.items():
        pnl1 = sum(s["pnl_1h"]) / len(s["pnl_1h"]) if s["pnl_1h"] else None
        pnl4 = sum(s["pnl_4h"]) / len(s["pnl_4h"]) if s["pnl_4h"] else None
        wr   = len([x for x in s["pnl_1h"] if x > 0]) / len(s["pnl_1h"]) * 100 if s["pnl_1h"] else None
        wr_str   = f"{wr:.0f}"   if wr   is not None else "?"
        pnl1_str = f"{pnl1:.3f}" if pnl1 is not None else "?"
        pnl4_str = f"{pnl4:.3f}" if pnl4 is not None else "?"
        summary_lines.append(
            f"  {sig}: n={s['count']}, win%={wr_str}, "
            f"avg_1h={pnl1_str}%, avg_4h={pnl4_str}%"
        )

    prompt_user = (
        f"Signal performance data:\n" + "\n".join(summary_lines) +
        f"\n\nHuidige PARAM_BOUNDS: {json.dumps(PARAM_BOUNDS)}" +
        "\n\nGebaseerd op de data: welke parameters moeten aangepast worden om de win-rate en "
        "avg_pnl te verbeteren? Geef JSON terug met de gewenste parameterwaarden. "
        "Blijf ALTIJD binnen de gegeven bounds. "
        '{"rsi_buy_threshold": 30, "stoploss_pct": 2.5, "reden": "..."}'
    )

    raw     = _ask_kimi(
        system="Je bent een trading parameter optimizer. Analyseer signal performance en optimaliseer parameters.",
        user=prompt_user,
        max_tokens=600,
    )
    suggestion = _parse_json(raw)
    if not suggestion or "reden" not in suggestion:
        log.info("Kimi gaf geen bruikbare aanbeveling.")
        return

    reden  = suggestion.pop("reden", "Automatische optimalisatie door OpenClaw")
    params = _clamp_params({k: v for k, v in suggestion.items() if k in PARAM_BOUNDS})

    if not params:
        log.info("Geen geldige parameters in Kimi aanbeveling.")
        return

    log.info(f"Kimi aanbeveling: {params} — reden: {reden}")

    # Dien proposal in
    proposal_resp = _api_post("/config/propose", {
        "agent":  "OpenClaw",
        "params": params,
        "reason": f"[Auto] {reden}",
    })
    if not proposal_resp:
        log.error("Proposal indienen mislukt.")
        return

    pid = proposal_resp.get("proposal_id")
    log.info(f"Proposal #{pid} ingediend: {params}")

    # Toepassen?
    if pid and _can_apply():
        apply_resp = _api_post(f"/proposals/{pid}/apply", {})
        if apply_resp:
            _record_apply()
            msg = (
                f"🤖 *OpenClaw Learning*\n\n"
                f"Proposal #{pid} toegepast:\n"
                + "\n".join(f"  • `{k}` = `{v}`" for k, v in params.items())
                + f"\n\n💡 _{reden}_"
            )
            _send_telegram(msg)
            log.info(f"Proposal #{pid} toegepast.")
        else:
            log.warning(f"Proposal #{pid} toepassen mislukt.")
    else:
        log.info(f"MAX_APPLIES_PER_DAY ({MAX_APPLIES_PER_DAY}) bereikt of geen pid, sla apply over.")


# ── Backtest loop ─────────────────────────────────────────────────────────

def backtest_loop() -> None:
    """Trigger historische backtest (1 maand) voor alle gevolgde coins."""
    log.info("=== Backtest loop gestart ===")
    state = _api_get("/state/latest")
    if not state:
        return
    coins = [c["symbol"] for c in state.get("coins", [])]
    if not coins:
        log.info("Geen coins om te backtesten.")
        return

    for sym in coins:
        log.info(f"Backtest triggeren voor {sym}...")
        result = _api_get(f"/backtest/historical/{sym}", {"months": 1, "interval": "1h"})
        if result:
            found = result.get("signals_found", 0)
            by    = result.get("by_signal", {})
            best  = max(by.keys(), key=lambda s: by[s].get("1h", {}).get("avg_pnl_pct", -99)) if by else "?"
            log.info(f"  {sym}: {found} signalen, beste={best}")
        time.sleep(2)  # beleefd wachten tussen API calls


# ── Main loop ─────────────────────────────────────────────────────────────

def main() -> None:
    log.info("OpenClaw Autonome Agent gestart.")
    log.info(f"  Learning interval:  {LEARN_INTERVAL}s")
    log.info(f"  Backtest interval:  {BACKTEST_INTERVAL}s")
    log.info(f"  Min signals:        {MIN_SIGNALS}")
    log.info(f"  Max applies/dag:    {MAX_APPLIES_PER_DAY}")
    log.info(f"  Control API:        {CONTROL_API_URL}")
    log.info(f"  Kimi model:         {KIMI_MODEL}")

    _send_telegram("🤖 *OpenClaw gestart* — learning agent actief.")

    last_learn    = 0.0
    last_backtest = 0.0
    last_decision = 0.0

    while True:
        now = time.time()

        # Morning briefing (elke iteratie checken, stuurt max 1x per dag om 07:00 UTC)
        try:
            morning_briefing()
        except Exception as e:
            log.error(f"Morning briefing fout: {e}")

        if now - last_learn >= LEARN_INTERVAL:
            try:
                learning_loop()
            except Exception as e:
                log.error(f"Learning loop fout: {e}")
            last_learn = now

        if now - last_backtest >= BACKTEST_INTERVAL:
            try:
                backtest_loop()
            except Exception as e:
                log.error(f"Backtest loop fout: {e}")
            last_backtest = now

        if now - last_decision >= DECISION_INTERVAL:
            try:
                autonomous_decision_loop()
            except Exception as e:
                log.error(f"Beslissingsengine fout: {e}")
            last_decision = now

        time.sleep(30)


if __name__ == "__main__":
    main()
