import os, time, requests, json
from openai import OpenAI
from telegram.common import get_updates, send_message, api_headers

CONTROL_API_URL      = os.getenv("CONTROL_API_URL", "http://control_api:8080")
INDICATOR_ENGINE_URL = os.getenv("INDICATOR_ENGINE_URL", "http://indicator_engine:8099")
ALLOWED = set([x.strip() for x in os.getenv("TELEGRAM_ALLOWED_USERS","").split(",") if x.strip()])
KIMI_API_KEY  = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL    = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5")

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_state():
    r = requests.get(f"{CONTROL_API_URL}/state/latest", headers=api_headers(), timeout=5)
    return r.json() if r.status_code == 200 else {}

def get_indicator_signal(symbol: str, interval: str = "1h") -> dict:
    try:
        r = requests.get(f"{INDICATOR_ENGINE_URL}/signal/{symbol}",
                         params={"interval": interval}, timeout=8)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}

def get_patterns(symbol: str) -> list:
    try:
        r = requests.get(f"{INDICATOR_ENGINE_URL}/patterns/{symbol}", timeout=8)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def web_search(query: str) -> str:
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
            topics = d.get("RelatedTopics", [])[:3]
            result = " | ".join(t.get("Text", "") for t in topics if t.get("Text"))
        return result[:500] if result else "Geen zoekresultaten gevonden."
    except Exception as e:
        return f"Zoekfout: {e}"

def ask_kimi(question: str, context: str = "") -> str:
    if not KIMI_API_KEY:
        return "Kimi niet geconfigureerd (KIMI_API_KEY ontbreekt)."
    try:
        client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
        system = (
            "Je bent Kimi, de AI-assistent van het OpenClaw crypto trading platform. "
            "Je praat met de eigenaar/trader van het platform via Telegram. "
            "Antwoord altijd in het Nederlands. Wees kort en concreet (max 200 woorden).\n\n"
            "JOUW ROL EN BEVOEGDHEDEN:\n"
            "- Je analyseert de markt en geeft concrete handelingsadviezen\n"
            "- Je MAG en MOET acties aanbevelen op basis van marktdata\n"
            "- Je hebt toegang tot 4 jaar historische patronen per coin (35.000+ candles)\n"
            "- De apex_engine voert automatisch trades uit op BloFin (demo modus)\n"
            "- De eigenaar kan via jou de engine sturen met commando's\n\n"
            "BESCHIKBARE COMMANDO'S:\n"
            "- /stop /start /pauzeer [min] — trading beheer\n"
            "- /status /coins /balance /perf — overzichten\n"
            "- /patroon SYMBOL — historische patroondata\n"
            "- /signal SYMBOL — indicator signaal met 4 jaar precedenten\n"
            "- /backtest SYMBOL — strategie backtest\n\n"
            "Gebruik de marktcontext en historische data die je krijgt. "
            "Als je een BUY/SELL kans ziet op basis van patronen, zeg dat DIRECT."
        )
        user_msg = question
        if context:
            user_msg = f"Marktcontext + historische data:\n{context}\n\nVraag: {question}"
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
        return f"Kimi fout: {e}"

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

# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_status(chat_id):
    state = get_state()
    coins = state.get("coins", [])
    ts    = (state.get("ts") or "?")[:19].replace("T", " ")
    kimi  = (state.get("kimi_last_scan") or "nog niet")[:19].replace("T", " ")
    flash = state.get("flash_triggers", [])
    lines = [f"Status {ts} UTC", f"Kimi scan: {kimi}", ""]
    for c in coins:
        sym    = c.get("symbol","?")
        price  = c.get("price", 0)
        chg    = c.get("change_pct", 0)
        rsi    = c.get("rsi")
        signal = c.get("signal", "HOLD")
        tf_b   = c.get("tf_bias", "")
        arrow  = "+" if chg >= 0 else "-"
        rsi_s  = f"RSI:{rsi:.0f}" if rsi else "RSI:?"
        tf_s   = f" TF:{tf_b}" if tf_b else ""
        lines.append(f"{arrow} {sym}: ${price:.4f} ({chg:+.2f}%) {signal} {rsi_s}{tf_s}")
    if flash:
        lines.append(f"\nFlash crashes (1u): {len(flash)}")
    send_message(chat_id, "\n".join(lines))

def cmd_coins(chat_id):
    coins = get_state().get("coins", [])
    if not coins:
        send_message(chat_id, "Kimi heeft nog geen coins geselecteerd.")
        return
    lines = ["Kimi's selectie:", ""]
    for i, c in enumerate(coins, 1):
        sym   = c.get("symbol","?")
        price = c.get("price", 0)
        chg   = c.get("change_pct", 0)
        vol   = c.get("volume_usdt", 0) / 1_000_000
        reden = c.get("kimi_reden", "—")
        rsi   = c.get("rsi")
        signal= c.get("signal", "HOLD")
        arrow = "+" if chg >= 0 else "-"
        rsi_str = f"{rsi:.0f}" if rsi else "?"
        lines.append(f"{i}. {arrow} {sym} ${price:.4f} ({chg:+.2f}%) {signal} RSI:{rsi_str}")
        lines.append(f"   {reden}")
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
        send_message(chat_id,
            f"Demo Account BloFin\n\n"
            f"Start:    $1.000\n"
            f"Balans:   ${bal:,.2f}\n"
            f"P&L:      {sign}${pnl:.2f} ({sign}{pnl_pct:.2f}%)\n"
            f"Win-rate: {wr}%\n"
            f"Trades:   {trades}"
        )
    except Exception as e:
        send_message(chat_id, f"Balance fout: {e}")

def cmd_perf(chat_id):
    try:
        r = requests.get(f"{CONTROL_API_URL}/signal-performance", headers=api_headers(),
                         params={"limit": 20}, timeout=5)
        rows = r.json()
        closed = [x for x in rows if x.get("pnl_1h_pct") is not None]
        if not closed:
            send_message(chat_id, "Nog geen afgeronde signalen.")
            return
        wins = [x for x in closed if x["pnl_1h_pct"] > 0]
        wr   = round(len(wins) / len(closed) * 100)
        avg  = round(sum(x["pnl_1h_pct"] for x in closed) / len(closed), 2)
        lines = [f"Signal Performance (laatste {len(closed)})\n",
                 f"Win-rate: {wr}%  Gem. P&L (1u): {avg:+.2f}%\n"]
        for x in closed[:8]:
            sym = x.get("symbol","?")
            sig = x.get("signal","?")
            p   = x.get("pnl_1h_pct", 0)
            icon = "+" if p > 0 else "-"
            lines.append(f"{icon} {sym} {sig}: {p:+.2f}%")
        send_message(chat_id, "\n".join(lines))
    except Exception as e:
        send_message(chat_id, f"Perf fout: {e}")

def cmd_patroon(chat_id, args: str):
    """Historische patroondata voor een coin: /patroon BTC"""
    parts  = args.strip().split()
    symbol = (parts[0].upper() if parts else "BTC")
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    send_message(chat_id, f"Patroondata ophalen voor {symbol}...")
    patterns = get_patterns(symbol)
    if not patterns:
        send_message(chat_id, f"Geen patroondata voor {symbol}. Is de indicator engine klaar?")
        return
    sorted_p = sorted(patterns, key=lambda x: x.get("win_rate", 0), reverse=True)
    top    = sorted_p[:3]
    bottom = sorted_p[-2:] if len(sorted_p) > 3 else []
    lines = [f"Historische patronen {symbol} ({len(patterns)} combinaties)\n"]
    lines.append("BESTE patronen:")
    for p in top:
        rz  = p.get("rsi_zone", "?")
        md  = p.get("macd_direction", "?")
        wr  = p.get("win_rate", 0)
        n   = p.get("n_trades", 0)
        avg = p.get("avg_pnl_1h", 0)
        lines.append(f"  RSI:{rz} MACD:{md} -> {wr:.0f}% win ({n} trades, avg {avg:+.2f}%)")
    if bottom:
        lines.append("\nSLECHTE patronen:")
        for p in bottom:
            rz  = p.get("rsi_zone", "?")
            md  = p.get("macd_direction", "?")
            wr  = p.get("win_rate", 0)
            n   = p.get("n_trades", 0)
            avg = p.get("avg_pnl_1h", 0)
            lines.append(f"  RSI:{rz} MACD:{md} -> {wr:.0f}% win ({n} trades, avg {avg:+.2f}%)")
    send_message(chat_id, "\n".join(lines))

def cmd_signal(chat_id, args: str):
    """Indicator signaal met historische precedenten: /signal BTC"""
    parts    = args.strip().split()
    symbol   = (parts[0].upper() if parts else "BTC")
    interval = parts[1] if len(parts) > 1 else "1h"
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    send_message(chat_id, f"Signaal ophalen voor {symbol} ({interval})...")
    sig = get_indicator_signal(symbol, interval)
    if not sig:
        send_message(chat_id, f"Geen signaaldata voor {symbol}.")
        return
    fp = sig.get("fingerprint", {})
    lines = [
        f"Signaal {symbol} ({interval})",
        f"",
        f"Signaal:     {sig.get('signaal','?')}",
        f"Confidence:  {sig.get('confidence',0):.0%}",
        f"Precedenten: {sig.get('precedenten',0)} (4 jaar data)",
        f"Win rate:    {sig.get('win_rate',0):.1f}%",
        f"Avg PnL 1h:  {sig.get('avg_pnl_1h',0):+.3f}%",
        f"Avg PnL 4h:  {sig.get('avg_pnl_4h',0):+.3f}%",
        f"Worst 1h:    {sig.get('worst_case_1h',0):+.3f}%",
        f"BTC trend:   {sig.get('btc_trend','?')}",
        f"",
        f"RSI zone:    {fp.get('rsi_zone','?')}",
        f"MACD:        {fp.get('macd_direction','?')}",
        f"BB positie:  {fp.get('bb_position','?')}",
        f"EMA:         {fp.get('ema_alignment','?')}",
        f"",
        f"{sig.get('reden','?')}",
    ]
    send_message(chat_id, "\n".join(lines))

def cmd_backtest(chat_id, args):
    parts  = args.strip().split()
    symbol = (parts[0].upper() if parts else "BTCUSDT")
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    interval = parts[1] if len(parts) > 1 else "4h"
    send_message(chat_id, f"Backtest {symbol} ({interval})...")
    try:
        r = requests.get(f"{CONTROL_API_URL}/backtest/{symbol}",
                         headers=api_headers(),
                         params={"interval": interval, "limit": 500}, timeout=30)
        d = r.json()
        if d.get("trades", 0) == 0:
            send_message(chat_id, f"{symbol}: geen trades in {interval} data.")
            return
        pf_ok = "OK" if d.get("profit_factor", 0) > 1.0 else "SLECHT"
        send_message(chat_id,
            f"Backtest {symbol} ({interval})\n"
            f"Trades: {d['trades']}  Win: {d['win_rate']}%\n"
            f"Profit factor: {d['profit_factor']} {pf_ok}\n"
            f"Max drawdown: {d['max_drawdown_pct']}%\n"
            f"Totaal rendement: {d['total_return_pct']}%"
        )
    except Exception as e:
        send_message(chat_id, f"Backtest fout: {e}")

def cmd_zoek(chat_id, query: str):
    if not query.strip():
        send_message(chat_id, "Gebruik: /zoek <zoekopdracht>")
        return
    send_message(chat_id, f"Zoeken naar: {query}...")
    web_result = web_search(query)
    if KIMI_API_KEY:
        antwoord = ask_kimi(f"Zoekopdracht: {query}\nResultaten: {web_result}")
    else:
        antwoord = web_result
    send_message(chat_id, f"{query}\n\n{antwoord}")

def cmd_clawbot(chat_id, args: str):
    arg = args.strip().lower()
    if not arg:
        try:
            r = requests.get(f"{CONTROL_API_URL}/clawbot/model", headers=api_headers(), timeout=5)
            d = r.json()
            model   = d.get("model", "?")
            premium = d.get("is_premium", False)
            send_message(chat_id,
                f"ClawBot Model\n\nHuidig: {model}\n"
                f"{'PREMIUM actief' if premium else 'Standaard Haiku'}\n\n"
                f"/clawbot sonnet — Sonnet 4.6\n/clawbot haiku — Haiku"
            )
        except Exception as e:
            send_message(chat_id, f"ClawBot status fout: {e}")
    elif arg == "sonnet":
        try:
            r = requests.post(f"{CONTROL_API_URL}/clawbot/model", headers=api_headers(),
                              json={"model": "sonnet"}, timeout=5)
            send_message(chat_id, "ClawBot -> Sonnet 4.6 geactiveerd." if r.status_code == 200 else f"Fout: {r.text}")
        except Exception as e:
            send_message(chat_id, f"Fout: {e}")
    elif arg == "haiku":
        try:
            r = requests.post(f"{CONTROL_API_URL}/clawbot/model", headers=api_headers(),
                              json={"model": "haiku"}, timeout=5)
            send_message(chat_id, "ClawBot -> Haiku geactiveerd." if r.status_code == 200 else f"Fout: {r.text}")
        except Exception as e:
            send_message(chat_id, f"Fout: {e}")
    else:
        send_message(chat_id, "/clawbot sonnet of /clawbot haiku")

def cmd_noodstop(chat_id):
    try:
        r = requests.post(f"{CONTROL_API_URL}/trading/halt", headers=api_headers(), timeout=5)
        if r.status_code == 200:
            send_message(chat_id, "NOODSTOP ACTIEF — alle trading gestopt. Gebruik /start om te hervatten.")
        else:
            send_message(chat_id, f"Noodstop mislukt: {r.text}")
    except Exception as e:
        send_message(chat_id, f"Noodstop fout: {e}")

def cmd_start_trading(chat_id):
    try:
        r = requests.post(f"{CONTROL_API_URL}/trading/resume", headers=api_headers(), timeout=5)
        if r.status_code == 200:
            send_message(chat_id, "Trading hervat.")
        else:
            send_message(chat_id, f"Hervatten mislukt: {r.text}")
    except Exception as e:
        send_message(chat_id, f"Hervatten fout: {e}")

def cmd_pauzeer(chat_id, args: str):
    parts = args.strip().split()
    try:
        minutes = int(parts[0]) if parts else 30
    except ValueError:
        minutes = 30
    try:
        r = requests.post(f"{CONTROL_API_URL}/trading/pause", headers=api_headers(),
                          json={"minutes": minutes, "reason": "handmatige pauze via Telegram"}, timeout=5)
        if r.status_code == 200:
            d = r.json()
            send_message(chat_id,
                f"Trading gepauzeerd {minutes} min\n"
                f"Hervat: {d.get('paused_until','?')[:19].replace('T',' ')} UTC"
            )
        else:
            send_message(chat_id, f"Pauze mislukt: {r.text}")
    except Exception as e:
        send_message(chat_id, f"Pauze fout: {e}")

def cmd_ok(chat_id, text: str):
    parts = text.strip().split()
    q_id = parts[1] if len(parts) > 1 else None
    if not q_id:
        send_message(chat_id, "Gebruik: /ok <q_id>")
        return
    try:
        requests.post(f"{CONTROL_API_URL}/trading/answer", headers=api_headers(),
                      json={"q_id": q_id, "antwoord": "ok"}, timeout=5)
        send_message(chat_id, f"OK doorgegeven voor {q_id}.")
    except Exception as e:
        send_message(chat_id, f"Fout: {e}")

def cmd_skip(chat_id, text: str):
    parts = text.strip().split()
    q_id = parts[1] if len(parts) > 1 else None
    if not q_id:
        send_message(chat_id, "Gebruik: /skip <q_id>")
        return
    try:
        requests.post(f"{CONTROL_API_URL}/trading/answer", headers=api_headers(),
                      json={"q_id": q_id, "antwoord": "skip"}, timeout=5)
        send_message(chat_id, f"Skip doorgegeven voor {q_id}.")
    except Exception as e:
        send_message(chat_id, f"Fout: {e}")

def cmd_tradingstatus(chat_id):
    try:
        r = requests.get(f"{CONTROL_API_URL}/trading/status", headers=api_headers(), timeout=5)
        d = r.json()
        if d.get("halted"):
            send_message(chat_id, "Trading: GESTOPT\nGebruik /start om te hervatten.")
        elif d.get("paused_until"):
            until = d["paused_until"][:19].replace("T", " ")
            send_message(chat_id, f"Trading: GEPAUZEERD tot {until} UTC")
        else:
            send_message(chat_id, "Trading: ACTIEF")
    except Exception as e:
        send_message(chat_id, f"Status fout: {e}")

def cmd_coingoedkeuren(chat_id, args: str):
    parts = args.strip().split()
    if not parts:
        try:
            r = requests.get(f"{CONTROL_API_URL}/coins/approved", headers=api_headers(), timeout=5)
            d = r.json()
            lines = ["Coin Goedkeuring\n"]
            if d.get("pending"):
                lines.append(f"Wachtend: {', '.join(d['pending'])}")
            if d.get("approved"):
                lines.append(f"Goedgekeurd: {', '.join(d['approved'])}")
            if d.get("rejected"):
                lines.append(f"Afgewezen: {', '.join(d['rejected'])}")
            send_message(chat_id, "\n".join(lines))
        except Exception as e:
            send_message(chat_id, f"Fout: {e}")
        return
    if len(parts) < 2:
        send_message(chat_id, "Gebruik: /coingoedkeuren ja SYMBOL  of  /coingoedkeuren nee SYMBOL")
        return
    actie  = parts[0].lower()
    symbol = parts[1].upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    if actie in ("ja", "yes"):
        action = "approve"
    elif actie in ("nee", "no"):
        action = "reject"
    else:
        send_message(chat_id, "Gebruik 'ja' of 'nee'")
        return
    try:
        r = requests.post(f"{CONTROL_API_URL}/coins/approved", headers=api_headers(),
                          json={"symbol": symbol, "action": action}, timeout=5)
        send_message(chat_id, f"{symbol}: {'GOEDGEKEURD' if action == 'approve' else 'AFGEWEZEN'}")
    except Exception as e:
        send_message(chat_id, f"Fout: {e}")

def cmd_sniper(chat_id, args: str):
    """Sniper bot beheer: /sniper dip BTC | /sniper short ETH rsi=68 | /sniper list | /sniper cancel <id>"""
    parts = args.strip().split()
    if not parts:
        send_message(chat_id,
            "Sniper Bot gebruik:\n"
            "/sniper dip BTC [rsi=28] — wacht op dip entry\n"
            "/sniper short ETH [rsi=68] — wacht op short entry\n"
            "/sniper breakout SOL — wacht op breakout\n"
            "/sniper niveau BTC target=80000 direction=dip\n"
            "/sniper list — actieve snipers\n"
            "/sniper cancel <id> — annuleer sniper\n"
            "/sniper reverse BTC [threshold=-5] — crash analyse"
        )
        return

    action = parts[0].lower()

    if action == "list":
        try:
            r = requests.get(f"{INDICATOR_ENGINE_URL}/sniper/list", timeout=10)
            snipers = r.json()
            if not snipers:
                send_message(chat_id, "Geen actieve snipers.")
                return
            lines = [f"Actieve snipers ({len(snipers)}):"]
            for s in snipers:
                rsi_now = f"RSI: {s['current_rsi']:.1f}" if s.get("current_rsi") else ""
                thr = f"drempel {s['rsi_threshold']}" if s.get("rsi_threshold") else ""
                target = f"target ${s['target_price']:,.2f}" if s.get("target_price") else ""
                lines.append(
                    f"• [{s['id']}] {s['symbol']} {s['mode'].upper()}"
                    f" — {thr or target} | {rsi_now} | nog {s.get('remaining_hours',0):.1f}u"
                )
            send_message(chat_id, "\n".join(lines))
        except Exception as e:
            send_message(chat_id, f"Fout: {e}")

    elif action == "cancel":
        if len(parts) < 2:
            send_message(chat_id, "Gebruik: /sniper cancel <id>")
            return
        sid = parts[1]
        try:
            r = requests.delete(f"{INDICATOR_ENGINE_URL}/sniper/{sid}", timeout=10)
            if r.status_code == 200:
                send_message(chat_id, f"Sniper {sid} geannuleerd.")
            else:
                send_message(chat_id, f"Sniper {sid} niet gevonden.")
        except Exception as e:
            send_message(chat_id, f"Fout: {e}")

    elif action == "reverse":
        symbol = parts[1].upper().replace("-", "") if len(parts) > 1 else "BTCUSDT"
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        threshold = -5.0
        for p in parts[2:]:
            if p.startswith("threshold="):
                try: threshold = float(p.split("=")[1])
                except: pass
        send_message(chat_id, f"Reverse backtest voor {symbol} (crashes ≤ {threshold}%)... even geduld.")
        try:
            r = requests.post(f"{INDICATOR_ENGINE_URL}/reverse-backtest",
                              json={"symbol": symbol, "crash_threshold_pct": threshold,
                                    "lookback_hours": [1, 4, 8, 24]}, timeout=30)
            data = r.json()
            lines = [
                f"Reverse Backtest {symbol}",
                f"Crash events: {data.get('crash_events_found', 0)}",
                f"Beste predictor: {data.get('best_predictor', 'n/a')}",
                "",
                "Pre-crash fingerprint:",
            ]
            for sig in data.get("combined_fingerprint", {}).get("signals", []):
                lines.append(f"• {sig}")
            if not data.get("combined_fingerprint", {}).get("signals"):
                lines.append("(geen consistent signaal gevonden)")
            send_message(chat_id, "\n".join(lines))
        except Exception as e:
            send_message(chat_id, f"Fout bij reverse backtest: {e}")

    elif action in ("dip", "short", "breakout", "niveau"):
        if len(parts) < 2:
            send_message(chat_id, f"Gebruik: /sniper {action} <SYMBOL>")
            return
        symbol = parts[1].upper().replace("-", "")
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        payload = {"symbol": symbol, "mode": action, "max_wait_hours": 24}

        for p in parts[2:]:
            if "=" in p:
                k, v = p.split("=", 1)
                try:
                    if k == "rsi": payload["rsi_threshold"] = float(v)
                    elif k == "target": payload["target_price"] = float(v)
                    elif k == "direction": payload["direction"] = v
                    elif k == "max_wait": payload["max_wait_hours"] = float(v)
                except ValueError:
                    pass

        try:
            r = requests.post(f"{INDICATOR_ENGINE_URL}/sniper/set", json=payload, timeout=10)
            data = r.json()
            s = data.get("sniper", {})
            msg = (
                f"Sniper gezet!\n"
                f"Symbol: {s.get('symbol')}\n"
                f"Mode: {s.get('mode','').upper()}\n"
                f"ID: {data.get('id')}\n"
                f"Max wacht: {s.get('max_wait_hours')}u\n"
            )
            if s.get("rsi_threshold"):
                msg += f"RSI drempel: {s['rsi_threshold']}\n"
            if s.get("target_price"):
                msg += f"Doelprijs: ${s['target_price']:,.4f} ({s.get('direction','any')})\n"
            msg += "\nIk stuur een bericht als de trigger afgaat."
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Fout bij instellen sniper: {e}")
    else:
        send_message(chat_id, f"Onbekende actie: {action}\nGebruik: /sniper list|dip|short|breakout|niveau|cancel|reverse")


def cmd_help(chat_id):
    send_message(chat_id,
        "OpenClaw Kimi Chat\n\n"
        "Marktoverzicht:\n"
        "/status — actueel overzicht\n"
        "/coins — Kimi's coin selectie\n"
        "/balance — demo account balans\n"
        "/perf — signal performance\n\n"
        "Historische data (4 jaar):\n"
        "/patroon [SYMBOL] — patroonanalyse bijv. /patroon BTC\n"
        "/signal [SYMBOL] [interval] — precedenten bijv. /signal ETH 4h\n"
        "/backtest [SYMBOL] [interval] — bijv. /backtest BTC 4h\n\n"
        "Sniper Bot:\n"
        "/sniper dip BTC [rsi=28] — wacht op dip entry\n"
        "/sniper short ETH [rsi=68] — wacht op short\n"
        "/sniper niveau BTC target=80000 — prijs alert\n"
        "/sniper list — actieve snipers\n"
        "/sniper cancel <id> — annuleer\n"
        "/sniper reverse BTC — crash analyse\n\n"
        "Trading beheer:\n"
        "/stop — NOODSTOP\n"
        "/start — hervat trading\n"
        "/pauzeer [minuten]\n"
        "/ok <q_id> — bevestig vraag\n"
        "/skip <q_id> — sla vraag over\n\n"
        "Overig:\n"
        "/zoek [query]\n"
        "/clawbot — Claude model instelling\n"
        "/coingoedkeuren\n"
        "/help\n\n"
        "Of stel gewoon een vraag!"
    )

# ── Main handler ──────────────────────────────────────────────────────────────

def handle(chat_id: str, user_id: str, text: str):
    if ALLOWED and user_id not in ALLOWED:
        send_message(chat_id, "Niet toegestaan.")
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
    elif text.startswith("/patroon"):
        cmd_patroon(chat_id, text[8:].strip())
    elif text.startswith("/signal"):
        cmd_signal(chat_id, text[7:].strip())
    elif text.startswith("/backtest"):
        cmd_backtest(chat_id, text[9:])
    elif text.startswith("/zoek"):
        cmd_zoek(chat_id, text[5:].strip())
    elif text.startswith("/stop"):
        cmd_noodstop(chat_id)
    elif text.startswith("/start"):
        cmd_start_trading(chat_id)
    elif text.startswith("/pauzeer"):
        cmd_pauzeer(chat_id, text[8:])
    elif text.startswith("/ok"):
        cmd_ok(chat_id, text)
    elif text.startswith("/skip"):
        cmd_skip(chat_id, text)
    elif text.startswith("/tradingstatus"):
        cmd_tradingstatus(chat_id)
    elif text.startswith("/clawbot"):
        cmd_clawbot(chat_id, text[8:].strip())
    elif text.startswith("/coingoedkeuren"):
        cmd_coingoedkeuren(chat_id, text[15:].strip())
    elif text.startswith("/sniper"):
        cmd_sniper(chat_id, text[7:].strip())
    elif text.startswith("/help"):
        cmd_help(chat_id)
    else:
        # Vrije vraag -> Kimi beantwoordt met marktcontext
        state   = get_state()
        context = build_context(state)
        send_message(chat_id, "Kimi denkt na...")
        antwoord = ask_kimi(text, context)
        send_message(chat_id, antwoord)

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
