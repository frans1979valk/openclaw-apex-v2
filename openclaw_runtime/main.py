"""
OpenClaw Runtime — Multi-agent orchestrator service.

Three agents run on schedule and can be triggered manually via HTTP:
  - research_agent  : market analysis (read-only)
  - strategy_agent  : parameter optimisation (propose-only)
  - risk_agent      : crash detection + trading pause/resume (write)

Each agent:
  1. Calls its allowed tools to gather context
  2. Passes context + system prompt to Kimi LLM
  3. Lets Kimi decide which follow-up tool calls to make (up to MAX_ROUNDS)
  4. Sends the final report to Telegram
"""

import os, json, logging, threading, time, importlib.util, sys
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [runtime] %(message)s",
)
log = logging.getLogger("runtime")

# ── Config ────────────────────────────────────────────────────────────────────
KIMI_API_KEY    = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL   = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
KIMI_MODEL      = os.getenv("KIMI_MODEL",    "moonshot-v1-32k")

TG_BOT_TOKEN    = os.getenv("TG_BOT_TOKEN_COORDINATOR", "")
TG_CHAT_ID      = os.getenv("TG_CHAT_ID", "")

RESEARCH_INTERVAL  = int(os.getenv("RESEARCH_INTERVAL",  "3600"))   # 1 h
STRATEGY_INTERVAL  = int(os.getenv("STRATEGY_INTERVAL",  "7200"))   # 2 h
RISK_INTERVAL      = int(os.getenv("RISK_INTERVAL",      "1800"))   # 30 min

TOOLS_DIR   = Path("/workspace/tools")
PROMPTS_DIR = Path("/workspace/prompts")
MAX_ROUNDS  = 4   # max agentic tool-call rounds per run

# ── Tool registry ─────────────────────────────────────────────────────────────
AGENT_TOOLS = {
    "research": ["tool_status", "tool_run_backtest", "tool_fetch_news"],
    "strategy": ["tool_status", "tool_run_backtest", "tool_fetch_news", "tool_propose_params"],
    "risk":     ["tool_status", "tool_fetch_news", "tool_pause_trading", "tool_resume_trading"],
}

def _load_tool(name: str):
    """Dynamically import a tool script and return its main() callable."""
    path = TOOLS_DIR / f"{name}.py"
    if not path.exists():
        raise FileNotFoundError(f"Tool not found: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def run_tool(name: str, kwargs: dict = None) -> str:
    """Run a tool and return its string output."""
    kwargs = kwargs or {}
    try:
        mod = _load_tool(name)
        if hasattr(mod, "main"):
            result = mod.main(**kwargs)
        else:
            result = json.dumps({"ok": False, "error": f"{name} has no main()"})
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        log.warning("Tool %s failed: %s", name, exc)
        return json.dumps({"ok": False, "error": str(exc)})

# ── Agent prompts ─────────────────────────────────────────────────────────────
def _load_prompt(agent: str) -> str:
    path = PROMPTS_DIR / f"{agent}_agent.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"Je bent de {agent} agent voor OpenClaw Apex. Analyseer de data en rapporteer."

# ── Kimi API ──────────────────────────────────────────────────────────────────
def kimi_chat(messages: list, tools_spec: list = None) -> dict:
    """Send messages to Kimi. Returns response message dict."""
    if not KIMI_API_KEY:
        return {"role": "assistant", "content": "[Kimi API key niet geconfigureerd]"}
    payload = {
        "model":    KIMI_MODEL,
        "messages": messages,
        "max_tokens": 1024,
    }
    if tools_spec:
        payload["tools"] = tools_spec
        payload["tool_choice"] = "auto"
    try:
        r = requests.post(
            f"{KIMI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {KIMI_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    except Exception as exc:
        log.error("Kimi API error: %s", exc)
        return {"role": "assistant", "content": f"[Kimi fout: {exc}]"}

def _tools_spec(tool_names: list) -> list:
    """Build minimal OpenAI-compatible tool specs for each tool name."""
    specs = []
    DESCRIPTIONS = {
        "tool_status":          "Haal actuele status op van de trading engine (markt, signalen, performance).",
        "tool_run_backtest":    "Voer een backtest uit voor een coin. Args: symbol (str), interval (str, bijv '1h').",
        "tool_fetch_news":      "Haal recente marktevents en nieuws op.",
        "tool_propose_params":  "Dien een parameter-voorstel in. Args: params (dict), reason (str).",
        "tool_apply_proposal":  "Pas een voorstel toe. Args: proposal_id (str).",
        "tool_pause_trading":   "Pauzeer de trading engine. Args: reason (str), duration_min (int).",
        "tool_resume_trading":  "Hervat de trading engine. Args: reason (str).",
    }
    PROPERTIES = {
        "tool_status":         {},
        "tool_run_backtest":   {"symbol": {"type": "string"}, "interval": {"type": "string", "default": "1h"}},
        "tool_fetch_news":     {},
        "tool_propose_params": {
            "params": {"type": "object"},
            "reason": {"type": "string"},
        },
        "tool_apply_proposal": {"proposal_id": {"type": "string"}},
        "tool_pause_trading":  {"reason": {"type": "string"}, "duration_min": {"type": "integer", "default": 30}},
        "tool_resume_trading": {"reason": {"type": "string"}},
    }
    for name in tool_names:
        specs.append({
            "type": "function",
            "function": {
                "name":        name,
                "description": DESCRIPTIONS.get(name, name),
                "parameters": {
                    "type": "object",
                    "properties": PROPERTIES.get(name, {}),
                    "required": [],
                },
            },
        })
    return specs

# ── Agent runner ──────────────────────────────────────────────────────────────
def run_agent(agent_type: str) -> str:
    """
    Run a single agent cycle.
    Returns the final text report.
    """
    log.info("Starting agent: %s", agent_type)
    allowed_tools = AGENT_TOOLS.get(agent_type, [])
    system_prompt = _load_prompt(agent_type)

    messages = [
        {"role": "system",  "content": system_prompt},
        {"role": "user",    "content": f"Start je {agent_type} analyse. Gebruik je tools en geef een rapport."},
    ]
    tools_spec = _tools_spec(allowed_tools)

    final_text = ""
    for round_num in range(MAX_ROUNDS):
        response = kimi_chat(messages, tools_spec=tools_spec)

        # Check for tool calls
        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            # Final answer
            final_text = response.get("content", "")
            break

        # Append assistant message with tool calls
        messages.append(response)

        # Execute each tool call
        for tc in tool_calls:
            fn_name   = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"].get("arguments", "{}"))
            except Exception:
                fn_args = {}

            # Security: only run allowed tools
            if fn_name not in allowed_tools:
                tool_result = json.dumps({"ok": False, "error": f"Tool {fn_name} niet toegestaan voor {agent_type}"})
            else:
                log.info("  [%s] calling tool %s(%s)", agent_type, fn_name, fn_args)
                tool_result = run_tool(fn_name, fn_args)

            messages.append({
                "role":        "tool",
                "tool_call_id": tc["id"],
                "content":     tool_result,
            })

        # If we've used all rounds, ask for final summary
        if round_num == MAX_ROUNDS - 2:
            messages.append({"role": "user", "content": "Geef nu je eindrapport (max 200 woorden)."})

    if not final_text:
        final_text = "[Agent gaf geen eindrapport]"

    log.info("Agent %s done. Report length: %d chars", agent_type, len(final_text))
    return final_text

# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(text: str, agent_type: str = "") -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    header = {"research": "🔍", "strategy": "📊", "risk": "🛡️"}.get(agent_type, "🤖")
    full = f"{header} *{agent_type.upper()} AGENT*\n\n{text}"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": full[:4000], "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as exc:
        log.warning("Telegram send failed: %s", exc)

# ── Periodic scheduler ────────────────────────────────────────────────────────
def _schedule_loop(agent_type: str, interval: int) -> None:
    log.info("Scheduler started: %s every %ds", agent_type, interval)
    while True:
        time.sleep(interval)
        try:
            report = run_agent(agent_type)
            send_telegram(report, agent_type)
        except Exception as exc:
            log.error("Scheduled %s failed: %s", agent_type, exc)

def start_schedulers() -> None:
    for agent, interval in [
        ("research", RESEARCH_INTERVAL),
        ("strategy", STRATEGY_INTERVAL),
        ("risk",     RISK_INTERVAL),
    ]:
        t = threading.Thread(target=_schedule_loop, args=(agent, interval), daemon=True)
        t.start()

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="OpenClaw Runtime", version="1.0.0")

@app.on_event("startup")
def on_startup():
    start_schedulers()
    log.info("OpenClaw Runtime started. Agents scheduled.")

@app.get("/health")
def health():
    return {"status": "ok", "service": "openclaw_runtime"}

class AgentTriggerResponse(BaseModel):
    agent:  str
    report: str

@app.post("/agents/research", response_model=AgentTriggerResponse)
def trigger_research():
    """Handmatig research agent starten."""
    report = run_agent("research")
    send_telegram(report, "research")
    return {"agent": "research", "report": report}

@app.post("/agents/strategy", response_model=AgentTriggerResponse)
def trigger_strategy():
    """Handmatig strategy agent starten."""
    report = run_agent("strategy")
    send_telegram(report, "strategy")
    return {"agent": "strategy", "report": report}

@app.post("/agents/risk", response_model=AgentTriggerResponse)
def trigger_risk():
    """Handmatig risk agent starten."""
    report = run_agent("risk")
    send_telegram(report, "risk")
    return {"agent": "risk", "report": report}

@app.get("/agents/status")
def agent_status():
    return {
        "agents": ["research", "strategy", "risk"],
        "intervals": {
            "research": RESEARCH_INTERVAL,
            "strategy": STRATEGY_INTERVAL,
            "risk":     RISK_INTERVAL,
        },
        "tools_dir":   str(TOOLS_DIR),
        "prompts_dir": str(PROMPTS_DIR),
    }
