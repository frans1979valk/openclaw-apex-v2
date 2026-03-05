import os, time, requests
from telegram.common import send_message, api_headers

CHAT_ID         = os.getenv("TELEGRAM_CHAT_ID", "")
CONTROL_API_URL = os.getenv("CONTROL_API_URL", "http://control_api:8080")
REPORT_INTERVAL = int(os.getenv("REPORT_INTERVAL", "300"))

SIGNAL_EMOJI = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "⚪ HOLD"}

def format_overview(state: dict) -> str:
    ts       = (state.get("ts") or "?")[:19].replace("T", " ")
    coins    = state.get("coins", [])
    kimi_ts  = (state.get("kimi_last_scan") or "nog niet")[:19].replace("T", " ")

    lines = [
        f"📊 *Apex Trading — {ts} UTC*",
        f"🤖 Kimi scan: {kimi_ts}",
        f"📌 Coins: {len(coins)}",
        "─────────────────────",
    ]
    for c in coins:
        sym    = c.get("symbol", "?")
        price  = c.get("price", 0)
        chg    = c.get("change_pct", 0)
        vol    = c.get("volume_usdt", 0) / 1_000_000
        rsi    = c.get("rsi")
        signal = c.get("signal", "HOLD")
        reden  = c.get("kimi_reden", "")

        chg_arrow = "🟢" if chg >= 0 else "🔴"
        sig_txt   = SIGNAL_EMOJI.get(signal, "⚪")

        lines.append(f"{chg_arrow} *{sym}*: ${price:.4f}  ({chg:+.2f}%)  Vol:{vol:.1f}M")
        rsi_txt = f"RSI:{rsi:.0f}" if rsi else "RSI:—"
        lines.append(f"   {sig_txt}  |  {rsi_txt}")
        if reden:
            lines.append(f"   💡 _{reden}_")
        lines.append("")
    lines.append("Mode: demo  |  Exchange: BloFin")
    return "\n".join(lines)

def main():
    last_report = 0.0
    while True:
        try:
            now = time.time()
            if CHAT_ID and (now - last_report) >= REPORT_INTERVAL:
                r = requests.get(f"{CONTROL_API_URL}/state/latest",
                                 headers=api_headers(), timeout=5)
                if r.status_code == 200:
                    send_message(CHAT_ID, format_overview(r.json()))
                    last_report = now
        except Exception as e:
            print(f"[coordinator] fout: {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()
