"""
Market Oracle — Macro-economische analyse engine.

Leest publieke RSS feeds, Yahoo Finance en nieuws.
Output: structured JSON met short/medium/long-term outlook + confidence.
Geen API keys, geen exchange keys, geen LLM keys.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
import yfinance as yf
from bs4 import BeautifulSoup

log = logging.getLogger("oracle")

# ── RSS feeds (publiek) ──────────────────────────────────────────────────────
RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/topNews",
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

# ── Sentiment keywords ───────────────────────────────────────────────────────
BEARISH_WORDS = {
    "crash", "plunge", "tumble", "recession", "default", "collapse",
    "downgrade", "selloff", "sell-off", "bear", "fear", "panic",
    "inflation", "hawkish", "rate hike", "tariff", "war", "sanctions",
}
BULLISH_WORDS = {
    "rally", "surge", "boom", "recovery", "bull", "growth", "stimulus",
    "dovish", "rate cut", "easing", "optimism", "approval", "breakout",
    "adoption", "institutional",
}

# ── Yahoo Finance tickers ────────────────────────────────────────────────────
MACRO_TICKERS = {
    "btc": "BTC-USD",
    "eth": "ETH-USD",
    "gold": "GC=F",
    "oil": "CL=F",
    "sp500": "^GSPC",
    "dxy": "DX-Y.NYB",
    "vix": "^VIX",
}


def _fetch_rss(max_items: int = 30) -> list[dict]:
    """Haal recente items uit RSS feeds."""
    items = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_items // len(RSS_FEEDS)]:
                items.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "published": entry.get("published", ""),
                    "link": entry.get("link", ""),
                })
        except Exception as e:
            log.warning("RSS feed %s failed: %s", url, e)
    return items


def _score_text(text: str) -> float:
    """Simpele sentiment score: -1 (bearish) tot +1 (bullish)."""
    text_lower = text.lower()
    bear = sum(1 for w in BEARISH_WORDS if w in text_lower)
    bull = sum(1 for w in BULLISH_WORDS if w in text_lower)
    total = bear + bull
    if total == 0:
        return 0.0
    return (bull - bear) / total


def _fetch_prices(focus: list[str]) -> dict:
    """Haal recente prijzen op voor focus-tickers."""
    prices = {}
    for name in focus:
        ticker = MACRO_TICKERS.get(name.lower().strip())
        if not ticker:
            continue
        try:
            data = yf.Ticker(ticker)
            hist = data.history(period="5d")
            if not hist.empty:
                current = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[0])
                change_pct = ((current - prev) / prev) * 100
                prices[name] = {
                    "price": round(current, 2),
                    "change_5d_pct": round(change_pct, 2),
                }
        except Exception as e:
            log.warning("yfinance %s failed: %s", ticker, e)
    return prices


def _fetch_url_text(url: str) -> str:
    """Haal tekst op van een URL (max 5000 chars)."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "MarketOracle/1.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text[:5000]
    except Exception as e:
        log.warning("URL fetch %s failed: %s", url, e)
        return ""


def _outlook(score: float) -> str:
    if score > 0.2:
        return "bullish"
    elif score < -0.2:
        return "bearish"
    return "neutral"


def _confidence(score: float, n_sources: int) -> float:
    """Confidence gebaseerd op score sterkte en aantal bronnen."""
    base = min(abs(score), 1.0)
    source_factor = min(n_sources / 10, 1.0)
    return round(base * 0.7 + source_factor * 0.3, 2)


def _suggested_actions(short_score: float) -> list[str]:
    """Suggesties op basis van korte-termijn sentiment."""
    if short_score < -0.5:
        return ["PAUSE", "NO_BUY"]
    elif short_score < -0.2:
        return ["TIGHTEN_STOPLOSS"]
    elif short_score > 0.5:
        return ["RESUME"]
    return []


def analyze_event(event: str, focus: str = "btc,eth,gold") -> dict:
    """Analyseer een specifiek event met macro context."""
    focus_list = [f.strip() for f in focus.split(",") if f.strip()]

    # RSS context
    rss_items = _fetch_rss()
    rss_texts = [f"{i['title']} {i['summary']}" for i in rss_items]

    # Event + RSS sentiment
    all_text = event + " " + " ".join(rss_texts)
    short_score = _score_text(event)
    full_score = _score_text(all_text)
    long_score = full_score * 0.6  # long-term is gedempter

    # Prices
    prices = _fetch_prices(focus_list)

    # Key factors extraction (simple: top RSS titles)
    key_factors = [i["title"] for i in rss_items[:5]]
    key_factors.insert(0, event)

    n_sources = len(rss_items) + len(prices)

    return {
        "ok": True,
        "analysis": {
            "short_term": {"outlook": _outlook(short_score), "confidence": _confidence(short_score, n_sources)},
            "medium_term": {"outlook": _outlook(full_score), "confidence": _confidence(full_score, n_sources)},
            "long_term": {"outlook": _outlook(long_score), "confidence": _confidence(long_score, n_sources)},
        },
        "contrarian_risk": round(max(0, 1 - abs(short_score) - 0.3), 2),
        "key_factors": key_factors[:6],
        "suggested_actions": _suggested_actions(short_score),
        "prices": prices,
        "sources_count": n_sources,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def analyze_url(url: str) -> dict:
    """Analyseer een nieuwsartikel URL."""
    text = _fetch_url_text(url)
    if not text:
        return {"ok": False, "error": f"Kon URL niet laden: {url}"}
    score = _score_text(text)
    return {
        "ok": True,
        "analysis": {
            "short_term": {"outlook": _outlook(score), "confidence": _confidence(score, 1)},
            "medium_term": {"outlook": _outlook(score * 0.7), "confidence": _confidence(score * 0.7, 1)},
            "long_term": {"outlook": "neutral", "confidence": 0.3},
        },
        "contrarian_risk": round(max(0, 1 - abs(score) - 0.3), 2),
        "key_factors": [f"Analysis of: {url}"],
        "suggested_actions": _suggested_actions(score),
        "url": url,
        "text_length": len(text),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def full_scan() -> dict:
    """Volledige macro scan: RSS + alle tickers."""
    rss_items = _fetch_rss()
    all_text = " ".join(f"{i['title']} {i['summary']}" for i in rss_items)
    score = _score_text(all_text)
    prices = _fetch_prices(list(MACRO_TICKERS.keys()))

    return {
        "ok": True,
        "analysis": {
            "short_term": {"outlook": _outlook(score), "confidence": _confidence(score, len(rss_items))},
            "medium_term": {"outlook": _outlook(score * 0.8), "confidence": _confidence(score * 0.8, len(rss_items))},
            "long_term": {"outlook": _outlook(score * 0.5), "confidence": _confidence(score * 0.5, len(rss_items))},
        },
        "contrarian_risk": round(max(0, 1 - abs(score) - 0.3), 2),
        "key_factors": [i["title"] for i in rss_items[:8]],
        "suggested_actions": _suggested_actions(score),
        "prices": prices,
        "rss_items_count": len(rss_items),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
