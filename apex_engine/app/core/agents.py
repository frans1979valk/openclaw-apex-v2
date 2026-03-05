"""
AI Agent Workflow — Research → Strategy → Risk Auditor → Verification
Gebruikt Kimi K2.5 via NVIDIA API voor elke agent rol.
"""
import os, json, requests
from typing import Dict, List, Optional
from openai import OpenAI

KIMI_API_KEY  = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL    = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5")

def _ask_kimi(system: str, user: str, max_tokens: int = 1024) -> str:
    if not KIMI_API_KEY:
        return "{}"
    try:
        client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
        resp = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f'{{"error": "{e}"}}'

def _parse_json(text: str) -> dict:
    try:
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return {"raw": text}

# ─────────────────────────────────────────────────────────────
# Agent 1: Researcher — analyseert marktdata + backtest context
# ─────────────────────────────────────────────────────────────
def researcher_agent(coin_states: List[Dict], backtest_summaries: dict = None) -> Dict:
    summary = "\n".join(
        f"{c['symbol']}: prijs={c.get('price',0):.4f} 24h={c.get('change_pct',0):+.2f}% "
        f"RSI={c.get('rsi','?')} MACD_hist={c.get('macd_hist','?')} signal={c.get('signal','?')}"
        for c in coin_states
    )
    # Voeg historische backtest context toe als beschikbaar
    bt_context = ""
    if backtest_summaries:
        lines = []
        for sym, bt in backtest_summaries.items():
            for sig, stats in bt.get("by_signal", {}).items():
                lines.append(
                    f"  {sym} {sig}: {stats['count']}x getest, win-rate 1h={stats['win_rate_1h']}%, "
                    f"gem P&L 1h={stats['avg_pnl_1h']:+.3f}%"
                )
        if lines:
            bt_context = "\n\nHistorische backtest resultaten (uit DB):\n" + "\n".join(lines)

    raw = _ask_kimi(
        system="Je bent een crypto research analyst. Analyseer de marktdata én historische backtest resultaten objectief.",
        user=f"Analyseer deze coins:\n{summary}{bt_context}\n\n"
             f"Geef JSON terug: {{\"analyse\": \"...\", \"kansen\": [\"sym1\",\"sym2\"], \"risicos\": [\"...\"], "
             f"\"backtest_inzicht\": \"wat zeggen de historische resultaten over de beste strategie\"}}",
        max_tokens=600
    )
    return _parse_json(raw)

# ─────────────────────────────────────────────────────────────
# Agent 2: Strategy Agent — bepaalt concrete entry/exit regels
# ─────────────────────────────────────────────────────────────
def strategy_agent(research: Dict, coin_states: List[Dict]) -> Dict:
    kansen = research.get("kansen", [c["symbol"] for c in coin_states[:2]])
    raw = _ask_kimi(
        system="Je bent een crypto strategie expert. Maak concrete trading regels.",
        user=f"Research: {json.dumps(research, ensure_ascii=False)}\n"
             f"Kansen: {kansen}\n\n"
             f"Geef JSON: {{\"strategy\": \"naam\", \"entry\": \"conditie\", \"exit\": \"conditie\", "
             f"\"position_size_pct\": 5, \"stoploss_pct\": 3, \"takeprofit_pct\": 6}}",
        max_tokens=512
    )
    return _parse_json(raw)

# ─────────────────────────────────────────────────────────────
# Agent 3: Risk Auditor — controleert risico
# ─────────────────────────────────────────────────────────────
def risk_auditor_agent(strategy: Dict) -> Dict:
    raw = _ask_kimi(
        system="Je bent een risk auditor voor crypto trading. Wees kritisch.",
        user=f"Beoordeel deze strategie op risico:\n{json.dumps(strategy, ensure_ascii=False)}\n\n"
             f"Geef JSON: {{\"goedgekeurd\": true/false, \"reden\": \"...\", "
             f"\"max_drawdown_ok\": true/false, \"aanbevelingen\": [\"...\"]}}",
        max_tokens=512
    )
    return _parse_json(raw)

# ─────────────────────────────────────────────────────────────
# Agent 4: Verification Agent — finale validatie
# ─────────────────────────────────────────────────────────────
def verification_agent(research: Dict, strategy: Dict, risk: Dict) -> Dict:
    raw = _ask_kimi(
        system="Je bent een verificatie agent. Geef een finale go/no-go beslissing.",
        user=f"Research: {json.dumps(research, ensure_ascii=False)}\n"
             f"Strategie: {json.dumps(strategy, ensure_ascii=False)}\n"
             f"Risk audit: {json.dumps(risk, ensure_ascii=False)}\n\n"
             f"Geef JSON: {{\"beslissing\": \"GO\" of \"NO_GO\", \"vertrouwen_pct\": 75, "
             f"\"samenvatting\": \"...\"}}",
        max_tokens=512
    )
    return _parse_json(raw)

# ─────────────────────────────────────────────────────────────
# Volledige workflow
# ─────────────────────────────────────────────────────────────
def run_agent_workflow(coin_states: List[Dict], backtest_summaries: dict = None) -> Dict:
    """Voer de volledige Research→Strategy→Risk→Verify workflow uit."""
    print("[agents] Researcher...")
    research = researcher_agent(coin_states, backtest_summaries)

    print("[agents] Strategy agent...")
    strategy = strategy_agent(research, coin_states)

    print("[agents] Risk auditor...")
    risk = risk_auditor_agent(strategy)

    print("[agents] Verificatie...")
    verdict = verification_agent(research, strategy, risk)

    return {
        "research":  research,
        "strategy":  strategy,
        "risk":      risk,
        "verdict":   verdict,
    }
