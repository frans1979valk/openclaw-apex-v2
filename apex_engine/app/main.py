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
from .core.trigger_engine import TriggerEngine
from .core.news_monitor import NewsMonitor
from .core.pre_crash_detector import PreCrashDetector
from .core.btc_cascade import BtcCascadeDetector
from .core.exchange_intel import ExchangeIntel

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
PRE_CRASH_BUY_BLOCK    = int(os.getenv("PRE_CRASH_BUY_BLOCK", "60"))   # score >= dit → geen kopen
NEWS_POLL_INTERVAL     = int(os.getenv("NEWS_POLL_INTERVAL", "120"))   # seconden
EXCHANGE_INTEL_ENABLED = os.getenv("EXCHANGE_INTEL_ENABLED", "true").lower() == "true"

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

    # STAP 15-17: nieuwe modules
    trigger_engine  = TriggerEngine()
    news_monitor    = NewsMonitor(interval=NEWS_POLL_INTERVAL)
    pre_crash       = PreCrashDetector()
    btc_cascade     = BtcCascadeDetector()
    exchange_intel  = ExchangeIntel(cache_ttl=30)

    log_event(db_path, source="apex", level="info",
              title="Apex gestart (volledig + PerfectDay + STAP15-17)",
              payload={"symbol": SYMBOL})

    tracked_coins     = []
    last_kimi_scan    = 0.0
    last_agent_run    = 0.0
    last_order        = {}
    last_signal_log   = {}
    last_agent_result = {}
    last_pre_crash    = {}   # sym → laatste score

    # BTC Cascade handler — logt event naar DB
    def _on_cascade(coins, btc_drop_pct, urgentie, btc_price=0):
        syms = [c["symbol"] for c in coins]
        print(f"[cascade] BTC drop {btc_drop_pct:.1f}% → CASCADE SHORT: {syms} | urgentie={urgentie}")
        log_event(db_path, source="cascade", level="warning",
                  title=f"BTC Cascade SHORT gedetecteerd ({btc_drop_pct:.1f}%)",
                  payload={"coins": syms, "urgentie": urgentie, "btc_price": btc_price})

    btc_cascade.on_cascade(_on_cascade)

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
                # Update news monitor met gevolgde coins
                news_monitor.update_tracked([c["symbol"] for c in tracked_coins])

        # STAP 15: Nieuws monitor poll
        try:
            news_monitor.poll(trigger_engine=trigger_engine)
        except Exception as e:
            print(f"[news] Fout: {e}")

        coin_states = []
        for coin in tracked_coins:
            sym   = coin["symbol"]
            price = BinanceFeed(sym).get_last_price() or coin.get("price", 0.0)
            vol   = coin.get("volume_usdt", 0.0)

            # STAP 17: Exchange Intel (gewogen consensus)
            ex_consensus = 0.0
            ex_coinbase_lead = False
            if EXCHANGE_INTEL_ENABLED and "BTC" in sym:
                try:
                    ex = exchange_intel.get_consensus(sym)
                    ex_consensus     = ex.get("consensus", 0.0)
                    ex_coinbase_lead = ex.get("coinbase_lead", False)
                    if ex_consensus > 0:
                        price = ex_consensus   # gebruik gewogen prijs als beschikbaar
                except Exception:
                    pass

            bybit_price = BybitFeed(sym[:-4] + "-USDT").get_last_price()

            # STAP 16: Pre-crash score berekenen
            ind_preview = calc_indicators(sym, INDICATOR_INTERVAL) or {}
            crash_score = pre_crash.score(sym, price, rsi=ind_preview.get("rsi"), volume=vol)
            last_pre_crash[sym] = crash_score
            safe_to_buy = pre_crash.is_safe_to_buy(sym, threshold=PRE_CRASH_BUY_BLOCK)

            # STAP 17: BTC cascade detectie
            if "BTC" in sym:
                btc_cascade.update(sym, price)

            # Flash crash — IJZEREN WET: geen koop als crash score hoog
            flash_triggered = flash_detect.update(sym, price, vol)
            if flash_triggered and not _is_trading_halted() and safe_to_buy:
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
            elif flash_triggered and not safe_to_buy:
                print(f"[IJZEREN WET] {sym}: flash crash BUY GEBLOKKEERD — pre-crash score={crash_score}")

            # Indicatoren (alle 5 strategieën)
            ind = ind_preview
            signal         = ind.get("signal", "HOLD")
            active_signals = ind.get("active_signals", [])
            perfect_day    = ind.get("perfect_day", False)

            # IJZEREN WET: hoge crash score → geforceerd DANGER signaal
            if crash_score >= PRE_CRASH_BUY_BLOCK and signal not in ("HOLD", "DANGER"):
                signal = "DANGER"
                active_signals.append(f"⚠️PreCrash({crash_score:.0f})")

            # Multi-timeframe bevestiging (1h/4h/1d)
            mtf = calculate_multi(sym, signal, ind.get("rsi") or 50)
            if mtf["downgraded"] and signal not in ("HOLD", "DANGER"):
                signal = "HOLD"
                active_signals.append("⚠️MTF-Down")
            elif mtf["upgraded"] and signal not in ("DANGER",):
                signal = "MOMENTUM"
                active_signals.append("⬆️MTF-Up")

            # STAP 15: Trigger engine check
            try:
                trigger_engine.check(
                    symbol=sym,
                    price=price,
                    volume=vol,
                    signal=signal,
                    rsi=ind.get("rsi"),
                    pre_crash_score=crash_score,
                )
            except Exception:
                pass

            coin_states.append({
                "symbol":            sym,
                "price":             price,
                "price_bybit":       bybit_price,
                "price_consensus":   round(ex_consensus, 4) if ex_consensus else None,
                "coinbase_lead":     ex_coinbase_lead,
                "change_pct":        coin.get("change_pct", 0.0),
                "volume_usdt":       vol,
                "kimi_reden":        coin.get("kimi_reden", ""),
                "signal":            signal,
                "active_signals":    active_signals,
                "perfect_day":       perfect_day,
                "rsi":               ind.get("rsi"),
                "macd_hist":         ind.get("macd_hist"),
                "adx":               ind.get("adx"),
                "bb_width":          ind.get("bb_width"),
                "ema21":             ind.get("ema21"),
                "atr":               ind.get("atr"),
                "danger":            ind.get("danger", False),
                "flash_crash":       flash_triggered,
                "pre_crash_score":   crash_score,
                "cascade_active":    btc_cascade.is_cascade_active if "BTC" in sym else False,
                "tf_confirm":        mtf.get("confirm_score"),
                "tf_bias":           mtf.get("tf_bias"),
                "tf_detail":         mtf.get("tf_detail", {}),
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

            # Order logica — IJZEREN WET: geen koop als crash score te hoog
            order_signal = signal in ("PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM", "BUY")
            if order_signal and price and not flash_triggered and not ind.get("danger") \
               and safe_to_buy \
               and (now - last_order.get(sym, 0)) > ORDER_COOLDOWN \
               and not _is_trading_halted():
                try:
                    size = "2" if perfect_day else "1"
                    res = executor.place_market_buy(size=size)
                    log_order(db_path, executor="blofin_demo", symbol=sym,
                              side="buy", size=size, price=price, raw=res)
                    log_event(db_path, source="apex", level="info",
                              title=f"{signal} BUY {sym}",
                              payload={"price": price, "rsi": ind.get("rsi"),
                                       "signals": active_signals, "crash_score": crash_score})
                    last_order[sym] = now
                    print(f"[apex] {signal} BUY {sym} @ {price:.4f} | crash_score={crash_score:.0f}")
                except Exception as e:
                    log_event(db_path, source="apex", level="error",
                              title=f"Order fout {sym}", payload={"error": str(e)})

            evaluate_open_signals(db_path, sym, price)
            demo_evaluate_trades(db_path, sym, price)

        # Agent workflow
        if coin_states and (now - last_agent_run) > AGENT_INTERVAL:
            print("[apex] AI agent workflow...")
            try:
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
            "pre_crash_scores": last_pre_crash,
            "cascade_active": btc_cascade.is_cascade_active,
        })
        time.sleep(10)

if __name__ == "__main__":
    main()
