"""
STAP 15 — News Monitor (CryptoPanic API)

Monitort CryptoPanic voor breaking nieuws en filtert op gevolgde coins.
Stuurt een Telegram-melding + trigger_engine event bij PANIC of BULLISH nieuws.

Env vars:
  CRYPTOPANIC_TOKEN  — API key van cryptopanic.com (gratis beschikbaar)
  TG_BOT_TOKEN_COORDINATOR + TG_CHAT_ID — voor Telegram meldingen
"""
import os, time, requests, logging
from typing import Set, Optional

log = logging.getLogger("news_monitor")

CRYPTOPANIC_TOKEN = os.getenv("CRYPTOPANIC_TOKEN", "")
CRYPTOPANIC_URL   = "https://cryptopanic.com/api/v1/posts/"
TG_BOT_TOKEN      = os.getenv("TG_BOT_TOKEN_COORDINATOR", "")
TG_CHAT_ID        = os.getenv("TG_CHAT_ID", "")

# Sentimenten die een alert triggeren
PANIC_KINDS   = {"negative", "important"}   # bearish / panic news
BULLISH_KINDS = {"positive", "important"}   # bullish / buy signal news


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


class NewsMonitor:
    """
    Polt CryptoPanic API elke `interval` seconden.
    Filtert items op gevolgde coins en stuurt alerts bij relevante news.
    """

    def __init__(self, interval: int = 120):
        self.interval   = interval
        self._seen_ids: Set[int] = set()
        self._last_poll = 0.0
        self._tracked_symbols: Set[str] = set()   # bijv. {"BTC", "ETH"}

    def update_tracked(self, symbols: list) -> None:
        """Update de gevolgde coins (geef BTCUSDT → haalt BTC eruit)."""
        self._tracked_symbols = {s.replace("USDT", "").upper() for s in symbols}

    def poll(self, trigger_engine=None) -> list:
        """
        Polt CryptoPanic als het interval verstreken is.
        Geeft lijst van nieuwe relevante nieuwsitems terug.
        Accepteert optioneel een TriggerEngine om events te firen.
        """
        if time.time() - self._last_poll < self.interval:
            return []

        self._last_poll = time.time()

        if not CRYPTOPANIC_TOKEN:
            return []

        try:
            r = requests.get(
                CRYPTOPANIC_URL,
                params={
                    "auth_token": CRYPTOPANIC_TOKEN,
                    "public":     "true",
                    "kind":       "news",
                },
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("results", [])
        except Exception as e:
            log.warning(f"CryptoPanic API fout: {e}")
            return []

        new_alerts = []
        for item in items:
            item_id = item.get("id", 0)
            if item_id in self._seen_ids:
                continue
            self._seen_ids.add(item_id)
            if len(self._seen_ids) > 2000:
                self._seen_ids = set(list(self._seen_ids)[-1000:])

            title    = item.get("title", "")
            kind     = item.get("kind", "")
            votes    = item.get("votes", {})
            panic    = votes.get("negative", 0)
            positive = votes.get("positive", 0)
            domain   = (item.get("domain") or "")

            # Check of een gevolgde coin genoemd wordt
            currencies = [c.get("code", "").upper() for c in item.get("currencies", [])]
            relevant   = bool(self._tracked_symbols & set(currencies)) or not self._tracked_symbols

            if not relevant:
                continue

            is_panic   = panic > 5 or kind == "negative"
            is_bullish = positive > 10 and panic < 3

            if not (is_panic or is_bullish):
                continue

            alert = {
                "id":         item_id,
                "title":      title,
                "kind":       "PANIC" if is_panic else "BULLISH",
                "coins":      currencies,
                "panic_votes": panic,
                "bull_votes": positive,
                "url":        item.get("url", ""),
            }
            new_alerts.append(alert)

            # Fire trigger event
            if trigger_engine:
                trigger_engine._fire(
                    "news_alert",
                    title=title,
                    kind=alert["kind"],
                    coins=currencies,
                    panic_votes=panic,
                )

            # Telegram melding
            kind_emoji = "🚨" if is_panic else "📰"
            coin_str   = "/".join(currencies[:3]) if currencies else "Crypto"
            msg = (
                f"{kind_emoji} *{alert['kind']} nieuws — {coin_str}*\n\n"
                f"_{title}_\n\n"
                f"👍 {positive}  |  👎 {panic}  |  {domain}"
            )
            _send_telegram(msg)
            log.info(f"Nieuws alert: [{alert['kind']}] {title[:60]}")

        return new_alerts
