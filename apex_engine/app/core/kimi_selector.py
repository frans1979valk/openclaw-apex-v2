import os, json, requests
from typing import List, Dict, Set
from openai import OpenAI

KIMI_API_KEY  = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
KIMI_MODEL    = os.getenv("KIMI_MODEL", "moonshot-v1-32k")

CONTROL_API_URL   = os.getenv("CONTROL_API_URL", "http://control_api:8080")
CONTROL_API_TOKEN = os.getenv("CONTROL_API_TOKEN", "")
TG_BOT_TOKEN      = os.getenv("TG_BOT_TOKEN_COORDINATOR", "")
TG_CHAT_ID        = os.getenv("TG_CHAT_ID", "")


def _get_approved_coins() -> Set[str]:
    """Haal goedgekeurde extra coins op van control_api."""
    try:
        r = requests.get(
            f"{CONTROL_API_URL}/coins/approved",
            headers={"X-API-KEY": CONTROL_API_TOKEN},
            timeout=5,
        )
        if r.status_code == 200:
            return set(r.json().get("approved", []))
    except Exception:
        pass
    return set()


def _send_telegram(msg: str) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception:
        pass


# Bijhouden welke coins al gemeld zijn om spam te voorkomen
_already_notified: set = set()


def _notify_pending(symbol: str, ticker: dict):
    """Meldt een nieuwe coin als 'wachtend op goedkeuring' aan de control_api en via Telegram."""
    try:
        r = requests.post(
            f"{CONTROL_API_URL}/coins/pending",
            headers={"X-API-KEY": CONTROL_API_TOKEN},
            json={"symbol": symbol, "action": "pending"},
            timeout=5,
        )
        if r.status_code == 200:
            status = r.json().get("status", "")
            # Alleen Telegram melding als coin nieuw is (niet al eerder gemeld)
            if status == "pending" and symbol not in _already_notified:
                _already_notified.add(symbol)
                chg  = ticker.get("change_pct", 0)
                vol  = ticker.get("volume_usdt", 0) / 1_000_000
                price = ticker.get("price", 0)
                _send_telegram(
                    f"🪙 *Nieuwe coin gesignaleerd: {symbol}*\n\n"
                    f"Prijs: ${price:.4f}  |  24h: {chg:+.2f}%  |  Vol: {vol:.1f}M USDT\n"
                    f"Kimi vindt deze coin interessant maar heeft toestemming nodig.\n\n"
                    f"Gebruik /coingoedkeuren ja {symbol} om hem toe te staan."
                )
    except Exception:
        pass


def select_best_coins(tickers: List[Dict], top_n: int = 5) -> List[Dict]:
    """
    Vraag Kimi welke coins de meeste kansen hebben.

    Nieuwe coins (is_new_coin=True) worden NIET automatisch geselecteerd —
    ze worden voorgesteld via de control_api en vereisen Telegram goedkeuring.
    Alleen safe coins + door eigenaar goedgekeurde coins mogen worden geselecteerd.
    """
    if not KIMI_API_KEY or not tickers:
        # Fallback: alleen safe coins teruggeven
        return [t for t in tickers if not t.get("is_new_coin")][:top_n]

    # Haal goedgekeurde extra coins op
    extra_approved = _get_approved_coins()

    # Splits: safe/goedgekeurde coins vs. nieuwe (nog niet goedgekeurde) coins
    safe_tickers = [t for t in tickers if not t.get("is_new_coin") or t["symbol"] in extra_approved]
    new_tickers  = [t for t in tickers if t.get("is_new_coin") and t["symbol"] not in extra_approved]

    # Kimi mag alleen kiezen uit safe/goedgekeurde coins
    candidates = safe_tickers if safe_tickers else tickers[:top_n]

    summary_safe = "\n".join(
        f"{t['symbol']}: prijs={t['price']:.4f} USDT, "
        f"24h={t['change_pct']:+.2f}%, vol={t['volume_usdt']/1e6:.1f}M USDT"
        for t in candidates
    )

    # Voeg nieuwe coins toe als info (niet selecteerbaar)
    new_info = ""
    if new_tickers:
        new_lines = "\n".join(
            f"{t['symbol']}: 24h={t['change_pct']:+.2f}%, vol={t['volume_usdt']/1e6:.1f}M USDT"
            for t in new_tickers[:10]
        )
        new_info = (
            f"\n\nNIEUWE COINS (nog niet goedgekeurd — NIET selecteren, alleen vermelden):\n"
            f"{new_lines}"
        )

    prompt = f"""Je bent een crypto trading analyst. Hier zijn de beschikbare USDT pairs:

{summary_safe}{new_info}

Selecteer de {top_n} beste coins voor een korte termijn trade (minuten tot uren).
Kies ALLEEN uit de beschikbare coins (niet de nieuwe coins).
Als je een nieuwe coin veelbelovend vindt, vermeld dit dan in je reden.

Geef je antwoord UITSLUITEND als JSON array, geen extra tekst:
[{{"symbol":"BTCUSDT","reden":"korte reden"}}, ...]"""

    try:
        client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
        resp = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        picks = json.loads(raw)
        symbols = {p["symbol"] for p in picks}
        selected = [t for t in candidates if t["symbol"] in symbols]
        # Voeg Kimi's redenering toe
        reason_map = {p["symbol"]: p.get("reden", "") for p in picks}
        for t in selected:
            t["kimi_reden"] = reason_map.get(t["symbol"], "")

        # Nieuwe coins die Kimi interessant vond → markeer als pending en meld via Telegram
        for t in new_tickers:
            if any(t["symbol"] in p.get("reden", "") for p in picks):
                _notify_pending(t["symbol"], t)

        return selected[:top_n]
    except Exception as e:
        print(f"[kimi_selector] fout: {e} — gebruik top volume als fallback")
        return [t for t in candidates if not t.get("is_new_coin")][:top_n]
