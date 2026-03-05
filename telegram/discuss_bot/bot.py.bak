import os, time, requests
from telegram.common import get_updates, send_message, api_headers

CONTROL_API_URL = os.getenv("CONTROL_API_URL", "http://control_api:8080")
ALLOWED = set([x.strip() for x in os.getenv("TELEGRAM_ALLOWED_USERS","").split(",") if x.strip()])

def get_state():
    r = requests.get(f"{CONTROL_API_URL}/state/latest", headers=api_headers(), timeout=5)
    return r.json() if r.status_code == 200 else {}

def cmd_status(chat_id):
    state = get_state()
    coins = state.get("coins", [])
    ts    = (state.get("ts") or "?")[:19].replace("T", " ")
    kimi  = (state.get("kimi_last_scan") or "nog niet")[:19].replace("T", " ")
    flash = state.get("flash_triggers", [])
    lines = [f"📈 *Status — {ts} UTC*", f"🤖 Kimi scan: {kimi}", ""]
    for c in coins:
        sym    = c.get("symbol","?")
        price  = c.get("price", 0)
        chg    = c.get("change_pct", 0)
        rsi    = c.get("rsi")
        signal = c.get("signal", "HOLD")
        arrow  = "🟢" if chg >= 0 else "🔴"
        sig    = {"BUY":"🟢BUY","SELL":"🔴SELL","HOLD":"⚪HOLD"}.get(signal,"⚪")
        rsi_s  = f"RSI:{rsi:.0f}" if rsi else "RSI:—"
        lines.append(f"{arrow} *{sym}*: ${price:.4f} ({chg:+.2f}%) {sig} {rsi_s}")
    if flash:
        lines.append(f"\n⚡ Flash crashes (1u): {len(flash)}")
    send_message(chat_id, "\n".join(lines))

def cmd_coins(chat_id):
    coins = get_state().get("coins", [])
    if not coins:
        send_message(chat_id, "⏳ Kimi heeft nog geen coins geselecteerd.")
        return
    lines = ["🎯 *Kimi's selectie:*", ""]
    for i, c in enumerate(coins, 1):
        sym   = c.get("symbol","?")
        price = c.get("price", 0)
        chg   = c.get("change_pct", 0)
        vol   = c.get("volume_usdt", 0) / 1_000_000
        reden = c.get("kimi_reden", "—")
        rsi   = c.get("rsi")
        signal= c.get("signal", "HOLD")
        arrow = "🟢" if chg >= 0 else "🔴"
        sig   = {"BUY":"🟢BUY","SELL":"🔴SELL","HOLD":"⚪HOLD"}.get(signal,"⚪")
        lines.append(f"{i}. {arrow} *{sym}* ${price:.4f} ({chg:+.2f}%) Vol:{vol:.1f}M")
        lines.append(f"   {sig}  RSI:{rsi:.0f if rsi else '—'}")
        lines.append(f"   💡 {reden}")
        lines.append("")
    send_message(chat_id, "\n".join(lines))

def cmd_backtest(chat_id, args):
    parts  = args.strip().split()
    symbol = (parts[0].upper() if parts else "BTCUSDT")
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    interval = parts[1] if len(parts) > 1 else "4h"
    send_message(chat_id, f"⏳ Backtest {symbol} ({interval})...")
    try:
        r = requests.get(
            f"{CONTROL_API_URL}/backtest/{symbol}",
            headers=api_headers(),
            params={"interval": interval, "limit": 500},
            timeout=30
        )
        d = r.json()
        if d.get("trades", 0) == 0:
            send_message(chat_id, f"📊 {symbol}: geen trades gevonden in {interval} data.")
            return
        pf_ok = "✅" if d.get("profit_factor", 0) > 1.0 else "❌"
        send_message(chat_id,
            f"📊 *Backtest {symbol} ({interval})*\n"
            f"Trades: {d['trades']}  Win: {d['win_rate']}%\n"
            f"Profit factor: {d['profit_factor']} {pf_ok}\n"
            f"Max drawdown: {d['max_drawdown_pct']}%\n"
            f"Sharpe: {d['sharpe']}\n"
            f"Totaal rendement: {d['total_return_pct']}%"
        )
    except Exception as e:
        send_message(chat_id, f"❌ Backtest fout: {e}")

def cmd_help(chat_id):
    send_message(chat_id,
        "📋 *Commands:*\n"
        "/status — actueel overzicht\n"
        "/coins — Kimi's coin selectie\n"
        "/backtest [SYMBOL] [interval] — bijv. /backtest BTC 4h\n"
        "/propose — voorstel opslaan\n"
        "/apply <id> — voorstel uitvoeren\n"
        "/help — dit menu"
    )

def handle(chat_id: str, user_id: str, text: str):
    if ALLOWED and user_id not in ALLOWED:
        send_message(chat_id, "⛔ Niet toegestaan.")
        return
    text = text.strip()
    if text.startswith("/status"):
        cmd_status(chat_id)
    elif text.startswith("/coins"):
        cmd_coins(chat_id)
    elif text.startswith("/backtest"):
        cmd_backtest(chat_id, text[9:])
    elif text.startswith("/propose"):
        payload = {"agent": "DiscussBot", "params": {"note": "manual"}, "reason": "handmatig"}
        r = requests.post(f"{CONTROL_API_URL}/config/propose", headers=api_headers(), json=payload, timeout=5)
        send_message(chat_id, f"✅ Voorstel: {r.text}")
    elif text.startswith("/apply"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Gebruik: /apply <id>")
            return
        r = requests.post(f"{CONTROL_API_URL}/proposals/{int(parts[1])}/apply", headers=api_headers(), timeout=5)
        send_message(chat_id, f"🟢 Toegepast: {r.text}")
    else:
        cmd_help(chat_id)

def main():
    offset = None
    while True:
        try:
            data = get_updates(offset)
            for u in data.get("result", []):
                offset = u["update_id"] + 1
                msg  = u.get("message") or {}
                text = msg.get("text") or ""
                chat = msg.get("chat") or {}
                frm  = msg.get("from") or {}
                if text:
                    handle(str(chat.get("id","")), str(frm.get("id","")), text)
        except Exception:
            time.sleep(2)
        time.sleep(1)

if __name__ == "__main__":
    main()
