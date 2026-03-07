import os, time, requests
from datetime import datetime, timezone
from telegram.common import send_message, api_headers

CHAT_ID         = os.getenv("TELEGRAM_CHAT_ID", "")
CONTROL_API_URL = os.getenv("CONTROL_API_URL", "http://control_api:8080")
REPORT_INTERVAL = int(os.getenv("REPORT_INTERVAL", "300"))
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "22"))  # UTC uur voor dagrapport

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

def format_daily_pnl(stats: dict) -> str:
    balance     = stats.get("balance", 0)
    peak        = stats.get("peak_balance", 0)
    trades      = stats.get("total_trades", 0)
    wins        = stats.get("winning_trades", 0)
    volume      = stats.get("total_volume_usdt", 0)
    start_bal   = 1000.0  # standaard startkapitaal
    pnl_usdt    = balance - start_bal
    pnl_pct     = (balance / start_bal - 1) * 100 if start_bal > 0 else 0
    win_rate    = (wins / trades * 100) if trades > 0 else 0
    drawdown    = ((peak - balance) / peak * 100) if peak > 0 else 0
    emoji       = "📈" if pnl_usdt >= 0 else "📉"
    date_str    = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return (
        f"{emoji} *Dagrapport Apex Demo — {date_str}*\n"
        f"─────────────────────\n"
        f"💰 Balance: ${balance:.2f}  (start: ${start_bal:.0f})\n"
        f"📊 PnL: ${pnl_usdt:+.2f}  ({pnl_pct:+.1f}%)\n"
        f"🏆 Piek: ${peak:.2f}  |  DD: {drawdown:.1f}%\n"
        f"─────────────────────\n"
        f"🔄 Trades: {trades}  |  Wins: {wins}  ({win_rate:.0f}%)\n"
        f"💵 Volume: ${volume/1000:.1f}K USDT\n"
        f"─────────────────────\n"
        f"Mode: demo  |  Exchange: BloFin"
    )


def main():
    last_report    = 0.0
    last_daily     = 0
    while True:
        try:
            now     = time.time()
            now_utc = datetime.now(timezone.utc)

            # Periodiek marktrapport
            if CHAT_ID and (now - last_report) >= REPORT_INTERVAL:
                r = requests.get(f"{CONTROL_API_URL}/state/latest",
                                 headers=api_headers(), timeout=5)
                if r.status_code == 200:
                    send_message(CHAT_ID, format_overview(r.json()))
                    last_report = now

            # Dagelijks P&L rapport (elke dag om DAILY_REPORT_HOUR UTC)
            today_day = now_utc.day
            if (CHAT_ID and now_utc.hour == DAILY_REPORT_HOUR
                    and now_utc.minute < 1 and today_day != last_daily):
                r = requests.get(f"{CONTROL_API_URL}/balance",
                                 headers=api_headers(), timeout=5)
                if r.status_code == 200:
                    send_message(CHAT_ID, format_daily_pnl(r.json()))
                    print(f"[coordinator] Dagrapport verstuurd ({now_utc.date()})")
                    last_daily = today_day

        except Exception as e:
            print(f"[coordinator] fout: {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()
