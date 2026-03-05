import os, time, json
from datetime import datetime, timezone
from .core.state import write_state
from .core.db import (init_db, log_event, log_order, log_signal_entry,
                      evaluate_open_signals, get_backtest_summaries,
                      log_market_context, demo_virtual_buy, demo_evaluate_trades)
from .exchanges.blofin_demo import create_executor
from .exchanges.binance_feed import BinanceFeed
from .exchanges.bybit_feed import BybitFeed
from .core.kimi_selector import select_best_coins
from .core.indicators import calculate as calc_indicators, calculate_multi
from .core.flash_crash import FlashCrashDetector
from .core.agents import run_agent_workflow

SYMBOL             = os.getenv("SYMBOL", "XRP-USDT")
TRADING_MODE       = os.getenv("TRADING_MODE", "demo").lower()
EXECUTOR_MODE      = os.getenv("EXECUTOR_MODE", "blofin_demo").lower()
ALLOW_LIVE         = os.getenv("ALLOW_LIVE", "false").lower() == "true"
KIMI_SCAN_INTERVAL = int(os.getenv("KIMI_SCAN_INTERVAL", "300"))
AGENT_INTERVAL     = int(os.getenv("AGENT_INTERVAL", "1800"))
TOP_N              = int(os.getenv("KIMI_TOP_N", "5"))
INDICATOR_INTERVAL = os.getenv("INDICATOR_INTERVAL", "5m")
ORDER_COOLDOWN         = int(os.getenv("ORDER_COOLDOWN", "120"))
SIGNAL_LOG_COOLDOWN    = int(os.getenv("SIGNAL_LOG_COOLDOWN", "900"))  # 15 minuten

HALT_FILE = "/var/apex/trading_halt.json"


def _is_trading_halted() -> bool:
    """Lees trading halt state uit gedeeld bestand (geschreven door control_api)."""
    try:
        with open(HALT_FILE, "r") as f:
            d = json.load(f)
        if d.get("halted"):
            return True
        paused_until = d.get("paused_until")
        if paused_until:
            from datetime import timezone as tz
            until = datetime.fromisoformat(paused_until)
            if datetime.now(timezone.utc) < until:
                return True
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[apex] Halt-file leesfout: {e}")
    return False


def guardrails():
    if TRADING_MODE != "demo":
        raise RuntimeError("TRADING_MODE must be demo.")
    if EXECUTOR_MODE != "blofin_demo":
        raise RuntimeError("EXECUTOR_MODE must be blofin_demo.")
    if ALLOW_LIVE:
        raise RuntimeError("ALLOW_LIVE must stay false.")

def main():
    guardrails()
    db_path = "/var/apex/apex.db"
    init_db(db_path)
    executor     = create_executor(symbol=SYMBOL)
    flash_detect = FlashCrashDetector()
    log_event(db_path, source="apex", level="info",
              title="Apex gestart (volledig + PerfectDay)", payload={"symbol": SYMBOL})

    tracked_coins     = []
    last_kimi_scan    = 0.0
    last_agent_run    = 0.0
    last_order        = {}
    last_signal_log   = {}   # voorkomt spam: 15 min cooldown per (sym, signal)
    last_agent_result = {}

    while True:
        now = time.time()

        # Kimi scan
        if now - last_kimi_scan > KIMI_SCAN_INTERVAL:
            movers = BinanceFeed.get_top_movers(30)
            if movers:
                tracked_coins = select_best_coins(movers, TOP_N)
                last_kimi_scan = now
                log_event(db_path, source="kimi", level="info",
                          title="Coins bijgewerkt",
                          payload={"coins": [c["symbol"] for c in tracked_coins]})
                print(f"[apex] Kimi koos: {[c['symbol'] for c in tracked_coins]}")

        coin_states = []
        for coin in tracked_coins:
            sym   = coin["symbol"]
            price = BinanceFeed(sym).get_last_price() or coin.get("price", 0.0)
            bybit_price = BybitFeed(sym[:-4] + "-USDT").get_last_price()
            vol   = coin.get("volume_usdt", 0.0)

            # Flash crash
            flash_triggered = flash_detect.update(sym, price, vol)
            if flash_triggered and not _is_trading_halted():
                try:
                    res = executor.place_market_buy(size="1")
                    log_order(db_path, executor="blofin_demo", symbol=sym,
                              side="buy", size="1", price=price, raw=res)
                    log_event(db_path, source="flash_crash", level="warning",
                              title=f"Flash crash BUY {sym}", payload={"price": price})
                    last_order[sym] = now
                except Exception as e:
                    log_event(db_path, source="flash_crash", level="error",
                              title=f"Flash crash fout {sym}", payload={"error": str(e)})

            # Indicatoren (alle 5 strategieën)
            ind = calc_indicators(sym, INDICATOR_INTERVAL) or {}
            signal         = ind.get("signal", "HOLD")
            active_signals = ind.get("active_signals", [])
            perfect_day    = ind.get("perfect_day", False)

            # Multi-timeframe bevestiging (1h/4h/1d)
            mtf = calculate_multi(sym, signal, ind.get("rsi") or 50)
            if mtf["downgraded"] and signal not in ("HOLD", "DANGER"):
                signal = "HOLD"   # hogere TF bearish → niet handelen
                active_signals.append("⚠️MTF-Down")
            elif mtf["upgraded"]:
                signal = "MOMENTUM"
                active_signals.append("⬆️MTF-Up")

            coin_states.append({
                "symbol":         sym,
                "price":          price,
                "price_bybit":    bybit_price,
                "change_pct":     coin.get("change_pct", 0.0),
                "volume_usdt":    vol,
                "kimi_reden":     coin.get("kimi_reden", ""),
                "signal":         signal,
                "active_signals": active_signals,
                "perfect_day":    perfect_day,
                "rsi":            ind.get("rsi"),
                "macd_hist":      ind.get("macd_hist"),
                "adx":            ind.get("adx"),
                "bb_width":       ind.get("bb_width"),
                "ema21":          ind.get("ema21"),
                "atr":            ind.get("atr"),
                "danger":         ind.get("danger", False),
                "flash_crash":    flash_triggered,
                "tf_confirm":     mtf.get("confirm_score"),
                "tf_bias":        mtf.get("tf_bias"),
                "tf_detail":      mtf.get("tf_detail", {}),
            })

            # Signal performance logging — max 1x per 15 min per (coin+signaal)
            sig_key = (sym, signal)
            if signal in ("PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM", "BUY") and price \
               and (now - last_signal_log.get(sig_key, 0)) > SIGNAL_LOG_COOLDOWN:
                log_signal_entry(db_path, symbol=sym, signal=signal,
                                 entry_price=price, active_signals=active_signals)
                log_market_context(db_path, symbol=sym, signal=signal, entry_price=price,
                                   rsi_5m=ind.get("rsi"), tf_confirm_score=mtf.get("confirm_score"),
                                   tf_bias=mtf.get("tf_bias"), tf_detail=mtf.get("tf_detail", {}))
                demo_virtual_buy(db_path, symbol=sym, price=price, signal=signal)
                last_signal_log[sig_key] = now

            # Order logica — Perfect Day = dubbele size
            order_signal = signal in ("PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM", "BUY")
            if order_signal and price and not flash_triggered and not ind.get("danger") \
               and (now - last_order.get(sym, 0)) > ORDER_COOLDOWN \
               and not _is_trading_halted():
                try:
                    size = "2" if perfect_day else "1"  # dubbele size bij Perfect Day
                    res = executor.place_market_buy(size=size)
                    log_order(db_path, executor="blofin_demo", symbol=sym,
                              side="buy", size=size, price=price, raw=res)
                    log_event(db_path, source="apex", level="info",
                              title=f"{signal} BUY {sym}",
                              payload={"price": price, "rsi": ind.get("rsi"), "signals": active_signals})
                    last_order[sym] = now
                    print(f"[apex] {signal} BUY {sym} @ {price:.4f} | {active_signals}")
                except Exception as e:
                    log_event(db_path, source="apex", level="error",
                              title=f"Order fout {sym}", payload={"error": str(e)})

            # Evalueer eerdere open signalen + demo trades
            evaluate_open_signals(db_path, sym, price)
            demo_evaluate_trades(db_path, sym, price)

        # Agent workflow
        if coin_states and (now - last_agent_run) > AGENT_INTERVAL:
            print("[apex] AI agent workflow...")
            try:
                # Haal historische backtest context op voor betere AI beslissingen
                symbols = [c["symbol"] for c in coin_states]
                bt_summaries = get_backtest_summaries(db_path, symbols)
                if bt_summaries:
                    print(f"[agents] Backtest context gevonden voor: {list(bt_summaries.keys())}")
                result = run_agent_workflow(coin_states, bt_summaries)
                last_agent_result = result
                last_agent_run = now
                verdict = result.get("verdict", {})
                log_event(db_path, source="agents", level="info",
                          title=f"Agent: {verdict.get('beslissing','?')}",
                          payload=verdict)
            except Exception as e:
                print(f"[agents] Fout: {e}")

        write_state("/var/apex/bot_state.json", {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "mode":           TRADING_MODE,
            "executor":       EXECUTOR_MODE,
            "kimi_last_scan": datetime.fromtimestamp(last_kimi_scan, tz=timezone.utc).isoformat()
                              if last_kimi_scan else None,
            "agent_last_run": datetime.fromtimestamp(last_agent_run, tz=timezone.utc).isoformat()
                              if last_agent_run else None,
            "coins":          coin_states,
            "flash_triggers": flash_detect.get_recent_triggers(3600),
            "last_agent":     last_agent_result,
        })
        time.sleep(10)

if __name__ == "__main__":
    main()
