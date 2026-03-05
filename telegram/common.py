import os, requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CONTROL_API_URL = os.getenv("CONTROL_API_URL", "http://control_api:8080")
CONTROL_API_TOKEN = os.getenv("CONTROL_API_TOKEN", "")

def api_headers():
    return {"X-API-KEY": CONTROL_API_TOKEN}

def send_message(chat_id: str, text: str):
    if not TOKEN:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()
