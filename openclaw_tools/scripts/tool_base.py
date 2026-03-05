"""Gedeelde base voor alle OpenClaw tools."""
import os, requests, json, logging

CONTROL_API_BASE = os.getenv("CONTROL_API_URL", "http://control_api:8080")
CONTROL_API_TOKEN = os.getenv("CONTROL_API_TOKEN", "")
LOG_FILE = os.getenv("OPENCLAW_TOOLS_LOG", "/var/apex/openclaw_tools.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)

def api_headers() -> dict:
    return {"X-API-KEY": CONTROL_API_TOKEN, "Content-Type": "application/json"}

def api_get(path: str, params: dict = None) -> dict:
    r = requests.get(f"{CONTROL_API_BASE}{path}", headers=api_headers(), params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def api_post(path: str, body: dict = None) -> dict:
    r = requests.post(f"{CONTROL_API_BASE}{path}", headers=api_headers(), json=body or {}, timeout=10)
    r.raise_for_status()
    return r.json()

def success(data: dict) -> str:
    return json.dumps({"ok": True, **data}, ensure_ascii=False, indent=2)

def error(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False, indent=2)
