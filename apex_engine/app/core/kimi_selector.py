import os, json
from typing import List, Dict
from openai import OpenAI

KIMI_API_KEY  = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL    = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5")

def select_best_coins(tickers: List[Dict], top_n: int = 5) -> List[Dict]:
    """Vraag Kimi welke coins de meeste kansen hebben. Geeft lijst van dicts terug."""
    if not KIMI_API_KEY or not tickers:
        return tickers[:top_n]

    summary = "\n".join(
        f"{t['symbol']}: prijs={t['price']:.4f} USDT, "
        f"24h={t['change_pct']:+.2f}%, vol={t['volume_usdt']/1e6:.1f}M USDT"
        for t in tickers
    )

    prompt = f"""Je bent een crypto trading analyst. Hier zijn de top {len(tickers)} USDT pairs van Binance:

{summary}

Selecteer de {top_n} coins met de meeste kansen voor een korte termijn trade (minuten tot uren).
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
        selected = [t for t in tickers if t["symbol"] in symbols]
        # Voeg Kimi's redenering toe
        reason_map = {p["symbol"]: p.get("reden", "") for p in picks}
        for t in selected:
            t["kimi_reden"] = reason_map.get(t["symbol"], "")
        return selected[:top_n]
    except Exception as e:
        print(f"[kimi_selector] fout: {e} — gebruik top volume als fallback")
        return tickers[:top_n]
