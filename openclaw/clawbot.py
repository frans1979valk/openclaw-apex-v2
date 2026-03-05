"""
ClawBot — Claude Sonnet als strategische AI boven Kimi K2.5.

Reviewt Kimi's analyse + live performance data en geeft een definitieve
strategische beslissing voor het OpenClaw platform.

IJZEREN WET: Koop NOOIT tijdens een crash. SHORT is de enige juiste actie.
"""
import os, json, logging
from typing import Optional

log = logging.getLogger("clawbot")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

CLAWBOT_SYSTEM = """Je bent ClawBot, de strategische AI van het OpenClaw crypto trading platform.
Je werkt als tweede laag boven Kimi K2.5. Je krijgt Kimi's analyse, live marktdata en historische performance.

Je taak:
1. Beoordeel Kimi's advies kritisch op basis van de live data
2. Combineer signalen met historische performance (backtest, win rates)
3. Geef een definitieve strategische beslissing

IJZEREN WET (nooit overrulen):
- Koop ABSOLUUT NOOIT tijdens een flash crash of marktcrash
- Bij crash/pre-crash: SHORT is de ENIGE juiste actie
- Bij twijfel: AFWACHTEN is veiliger dan INZETTEN

Urgentieniveaus:
- LOW: reguliere situatie, geen haast
- MEDIUM: opvallend signaal, aandacht gewenst
- HIGH: sterk signaal of risico, snel reageren
- CRITICAL: noodstop of kans van het jaar, direct handelen

Antwoord ALTIJD als geldig JSON (geen extra tekst):
{
  "beslissing": "INZETTEN|VERMIJDEN|AFWACHTEN|SHORT",
  "coin": "BTCUSDT",
  "reden": "Korte strategische redenering (max 2 zinnen)",
  "urgentie": "LOW|MEDIUM|HIGH|CRITICAL",
  "confidence_pct": 75,
  "override_kimi": false,
  "override_reden": ""
}"""


def _parse_json(text: str) -> dict:
    try:
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except Exception:
                    continue
        return json.loads(text)
    except Exception:
        return {}


def ask_clawbot(
    kimi_output: dict,
    db_context: dict,
    live_perf: dict,
    situation: str = "normal",
) -> dict:
    """
    Vraag ClawBot (Claude Sonnet) om een strategische beslissing.

    Args:
        kimi_output:  Kimi's beslissing/analyse als dict
        db_context:   Database context (backtest summaries, historische win rates)
        live_perf:    Live performance statistieken (win rate, avg pnl, etc.)
        situation:    Situatietype: normal | market_crash | win_rate_crash |
                      perfect_day_2x | 48h_loss | pre_crash

    Returns:
        dict met beslissing, reden, urgentie, confidence_pct, override_kimi
        Leeg dict als ClawBot niet beschikbaar of fout.
    """
    if not ANTHROPIC_API_KEY:
        log.info("ANTHROPIC_API_KEY niet ingesteld — ClawBot overgeslagen (Kimi beslist).")
        return {}

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        user_msg = (
            f"Situatie: {situation}\n\n"
            f"Kimi's analyse:\n"
            f"{json.dumps(kimi_output, ensure_ascii=False, indent=2)}\n\n"
            f"Live performance:\n"
            f"{json.dumps(live_perf, ensure_ascii=False, indent=2)}\n\n"
            f"Historische database context (backtest/win rates):\n"
            f"{json.dumps(db_context, ensure_ascii=False, indent=2)}\n\n"
            "Geef je strategische beslissing als JSON."
        )

        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            system=CLAWBOT_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )

        raw = msg.content[0].text.strip()
        result = _parse_json(raw)

        if result:
            override = result.get("override_kimi", False)
            beslissing = result.get("beslissing", "?")
            urgentie = result.get("urgentie", "LOW")
            log.info(
                f"ClawBot beslissing: {beslissing} | urgentie={urgentie} | "
                f"override_kimi={override}"
            )
        else:
            log.warning(f"ClawBot: kon JSON niet parsen uit respons: {raw[:200]}")

        return result

    except Exception as e:
        log.error(f"ClawBot fout: {e}")
        return {}


def clawbot_available() -> bool:
    """Geeft True als ClawBot geconfigureerd is."""
    return bool(ANTHROPIC_API_KEY)
