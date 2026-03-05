import os, time, requests, json
from openai import OpenAI
from telegram.common import get_updates, send_message, api_headers

CONTROL_API_URL = os.getenv("CONTROL_API_URL", "http://control_api:8080")
ALLOWED = set([x.strip() for x in os.getenv("TELEGRAM_ALLOWED_USERS","").split(",") if x.strip()])
KIMI_API_KEY  = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL    = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5")

def get_state():
    r = requests.get(f"{CONTROL_API_URL}/state/latest", headers=api_headers(), timeout=5)
    return r.json() if r.status_code == 200 else {}

def web_search(query: str) -> str:
    """Zoek actuele info via DuckDuckGo Instant Answer API."""
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=8,
        )
        d = r.json()
        abstract = d.get("AbstractText", "")
        answer   = d.get("Answer", "")
        result   = answer or abstract
        if not result:
            # Fallback: gebruik RelatedTopics
            topics = d.get("RelatedTopics", [])[:3]
            result = " | ".join(t.get("Text", "") for t in topics if t.get("Text"))
        return result[:500] if result else "Geen zoekresultaten gevonden."
    except Exception as e:
        return f"Zoekfout: {e}"

def ask_kimi(question: str, context: str = "") -> str:
    if not KIMI_API_KEY:
        return "⚠️ Kimi niet geconfigureerd (KIMI_API_KEY ontbreekt)."
    try:
        client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
        system = (
            "Je bent een behulpzame crypto trading assistent van het OpenClaw platform. "
            "Antwoord altijd in het Nederlands. Wees kort en concreet (max 200 woorden). "
            "Gebruik de marktcontext als die beschikbaar is."
        )
        user_msg = question
        if context:
            user_msg = f"Marktcontext:\n{context}\n\nVraag: {question}"
        resp = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Kimi fout: {e}"

def build_context(state: dict) -> str:
    coins = state.get("coins", [])
    ts    = (state.get("ts") or "?")[:19].replace("T", " ")
    lines = [f"Tijdstip: {ts} UTC"]
    for c in coins[:5]:
        lines.append(
            f"{c.get('symbol','?')}: {c.get('signal','?')} "
            f"RSI={c.get('rsi',0) or 0:.0f} prijs=${c.get('price',0):.4f} "
            f"change={c.get('change_pct',0):+.2f}%"
        )
    return "\n".join(lines)

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
        tf_b   = c.get("tf_bias", "")
        arrow  = "🟢" if chg >= 0 else "🔴"
        sig    = {"BUY":"🟢BUY","SELL":"🔴SELL","HOLD":"⚪HOLD",
                  "PERFECT_DAY":"⭐PERFECT DAY","BREAKOUT_BULL":"🚀BREAKOUT",
                  "MOMENTUM":"📈MOMENTUM","DANGER":"⚠️DANGER"}.get(signal,"⚪")
        rsi_s  = f"RSI:{rsi:.0f}" if rsi else "RSI:—"
        tf_s   = f" | TF:{tf_b}" if tf_b else ""
        lines.append(f"{arrow} *{sym}*: ${price:.4f} ({chg:+.2f}%) {sig} {rsi_s}{tf_s}")
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
        tf_c  = c.get("tf_confirm")
        arrow = "🟢" if chg >= 0 else "🔴"
        sig   = {"BUY":"🟢BUY","SELL":"🔴SELL","HOLD":"⚪HOLD",
                 "PERFECT_DAY":"⭐PERFECT DAY","BREAKOUT_BULL":"🚀BREAKOUT",
                 "MOMENTUM":"📈MOMENTUM","DANGER":"⚠️DANGER"}.get(signal,"⚪")
        lines.append(f"{i}. {arrow} *{sym}* ${price:.4f} ({chg:+.2f}%) Vol:{vol:.1f}M")
        rsi_str = f"{rsi:.0f}" if rsi else "—"
        tf_str  = f" | TF:{tf_c}%" if tf_c is not None else ""
        lines.append(f"   {sig}  RSI:{rsi_str}{tf_str}")
        lines.append(f"   💡 {reden}")
        lines.append("")
    send_message(chat_id, "\n".join(lines))

def cmd_balance(chat_id):
    try:
        r = requests.get(f"{CONTROL_API_URL}/balance", headers=api_headers(), timeout=5)
        d = r.json()
        bal     = d.get("balance", 1000)
        pnl     = d.get("pnl_total_usdt", 0)
        pnl_pct = d.get("pnl_total_pct", 0)
        wr      = d.get("win_rate_pct", 0)
        trades  = d.get("total_orders", 0)
        sign    = "+" if pnl >= 0 else ""
        arrow   = "📈" if pnl >= 0 else "📉"
        send_message(chat_id,
            f"💰 *Demo Account — BloFin Paper*\n\n"
            f"Start:   $1.000\n"
            f"Balans:  ${bal:,.2f}\n"
            f"{arrow} P&L:    {sign}${pnl:.2f} ({sign}{pnl_pct:.2f}%)\n"
            f"Win-rate: {wr}%\n"
            f"Trades:   {trades}"
        )
    except Exception as e:
        send_message(chat_id, f"❌ Balance fout: {e}")

def cmd_perf(chat_id):
    try:
        r = requests.get(f"{CONTROL_API_URL}/signal-performance", headers=api_headers(),
                         params={"limit": 20}, timeout=5)
        rows = r.json()
        closed = [x for x in rows if x.get("pnl_1h_pct") is not None]
        if not closed:
            send_message(chat_id, "⏳ Nog geen afgeronde signalen.")
            return
        wins = [x for x in closed if x["pnl_1h_pct"] > 0]
        wr   = round(len(wins) / len(closed) * 100)
        avg  = round(sum(x["pnl_1h_pct"] for x in closed) / len(closed), 2)
        lines = [f"📊 *Signal Performance* (laatste {len(closed)})\n",
                 f"Win-rate: {wr}%  |  Gem. P&L (1u): {avg:+.2f}%\n"]
        for x in closed[:8]:
            sym = x.get("symbol","?")
            sig = x.get("signal","?")
            p   = x.get("pnl_1h_pct", 0)
            icon = "✅" if p > 0 else "❌"
            lines.append(f"{icon} {sym} {sig}: {p:+.2f}%")
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_message(chat_id, f"❌ Perf fout: {e}")

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

def cmd_zoek(chat_id, query: str):
    """Zoek actuele informatie op het web en beantwoord de vraag."""
    if not query.strip():
        send_message(chat_id, "Gebruik: /zoek <zoekopdracht>  bijv. /zoek Bitcoin nieuws")
        return
    send_message(chat_id, f"🔍 Zoeken naar: {query}...")
    web_result = web_search(query)
    if KIMI_API_KEY:
        antwoord = ask_kimi(
            f"Beantwoord de volgende zoekopdracht op basis van de zoekresultaten:\n"
            f"Zoekopdracht: {query}\n"
            f"Resultaten: {web_result}",
        )
    else:
        antwoord = web_result
    send_message(chat_id, f"🔍 *{query}*\n\n{antwoord}")

def cmd_help(chat_id):
    send_message(chat_id,
        "📋 *OpenClaw Discuss Bot*\n\n"
        "/status — actueel marktoverzicht\n"
        "/coins — Kimi's coin selectie\n"
        "/balance — demo account balans\n"
        "/perf — signal performance stats\n"
        "/backtest [SYMBOL] [interval] — bijv. /backtest BTC 4h\n"
        "/zoek [query] — zoek actuele info op\n"
        "/help — dit menu\n\n"
        "💬 _Of stel gewoon een vraag over de markt!_"
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
    elif text.startswith("/balance"):
        cmd_balance(chat_id)
    elif text.startswith("/perf"):
        cmd_perf(chat_id)
    elif text.startswith("/backtest"):
        cmd_backtest(chat_id, text[9:])
    elif text.startswith("/zoek"):
        cmd_zoek(chat_id, text[5:].strip())
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
    elif text.startswith("/help") or text.startswith("/start"):
        cmd_help(chat_id)
    else:
        # Vrije vraag → Kimi beantwoordt met marktcontext
        state   = get_state()
        context = build_context(state)
        send_message(chat_id, "🤔 Kimi denkt na...")
        antwoord = ask_kimi(text, context)
        send_message(chat_id, f"🤖 {antwoord}")

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
