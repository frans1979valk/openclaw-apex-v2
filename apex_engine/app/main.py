import os, time, json
from datetime import datetime, timezone
import urllib.request
from .core.state import write_state
from .core.db import (init_db, log_event, log_order, log_signal_entry,
                      evaluate_open_signals, get_backtest_summaries,
                      log_market_context, demo_virtual_buy, demo_evaluate_trades,
                      count_open_demo_positions)
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
from .core.data_logger import DataLogger

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
STATE_PATH = "/var/apex/bot_state.json"
RSI_BUY_THRESHOLD = float(os.getenv("RSI_BUY_THRESHOLD", "35"))  # default: geen koop boven RSI 35
INDICATOR_ENGINE_URL = os.getenv("INDICATOR_ENGINE_URL", "http://indicator_engine:8099")


def _get_btc_ema200_ok() -> bool:
    """Haal BTC 4h EMA200 op via indicator_engine. True = prijs boven EMA200 (bullish)."""
    try:
        url = f"{INDICATOR_ENGINE_URL}/indicators/BTCUSDT?interval=4h"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        ema200 = data.get("ema200")
        close = data.get("close")
        if ema200 and close:
            return float(close) > float(ema200)
    except Exception:
        pass
    return True   # bij fout: niet blokkeren


def _send_pattern_feedback(symbol: str, fingerprint: dict, pnl_1h: float,
                            interval: str = "1h") -> None:
    """Stuur trade resultaat terug naar indicator_engine als nieuw patroon-datapunt."""
    try:
        payload = json.dumps({
            "symbol": symbol, "interval": interval,
            "pnl_1h": round(pnl_1h, 4), "fingerprint": fingerprint,
        }).encode()
        req_obj = urllib.request.Request(
            f"{INDICATOR_ENGINE_URL}/feedback",
            data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req_obj, timeout=3):
            pass
        print(f"[feedback] {symbol} pnl_1h={pnl_1h:.3f}% terugestuurd naar indicator_engine")
    except Exception as e:
        print(f"[feedback] Fout bij terugsturen {symbol}: {e}")


def _get_pattern_signal(symbol: str, interval: str = "1h") -> dict:
    """Vraag indicator_engine om een pattern-based signaal. Geeft {} bij fout."""
    try:
        sym_b = symbol.replace("-", "")  # XRP-USDT → XRPUSDT
        url = f"{INDICATOR_ENGINE_URL}/signal/{sym_b}?interval={interval}"
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _get_config_overrides() -> dict:
    """Lees config_overrides uit bot_state.json (gezet door control_api proposals)."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("config_overrides") or {}
    except Exception:
        return {}


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
    data_logger     = DataLogger(db_path)

    log_event(db_path, source="apex", level="info",
              title="Apex gestart (volledig + PerfectDay + STAP15-17 + DataLogger)",
              payload={"symbol": SYMBOL})

    tracked_coins     = []
    last_kimi_scan    = 0.0
    last_agent_run    = 0.0
    last_order        = {}
    last_signal_log   = {}
    last_agent_result = {}
    last_pre_crash    = {}   # sym → laatste score

    # BTC filter state — bijhouden van BTC trend voor altcoin filtering
    btc_state         = {"ema_bull": None, "rsi": None, "above_ema200": True}
    BTC_FILTER_EXEMPT = {"BTCUSDT", "ETHUSDT", "DOGEUSDT", "LTCUSDT"}
    BTC_EMA200_REFRESH = 900   # elke 15 min EMA200 checken
    last_ema200_check  = 0.0

    # Live pattern feedback — fingerprint opslaan bij koop, terugsturen na 1h
    # {symbol: {"fingerprint": dict, "entry_price": float, "buy_time": float, "interval": str}}
    _pending_feedback: dict = {}
    BTC_RSI_THRESHOLD = 45.0

    # Signal blacklist — blokkeer (coin, signal) combos met slechte historische PnL
    SIGNAL_BLACKLIST_PNL_THRESHOLD = -0.40   # avg_pnl_1h < dit → blokkeren
    SIGNAL_BLACKLIST_MIN_TRADES    = 10      # minimaal N trades voor betrouwbare data
    SIGNAL_BLACKLIST_REFRESH       = 1800    # elke 30 min verversen
    signal_blacklist: set = set()            # set van (symbol, signal) tuples
    last_blacklist_refresh = 0.0

    # Coin profielen — per-coin RSI threshold op basis van historische win rate
    COIN_PROFILE_REFRESH   = 3600     # elk uur verversen
    COIN_PROFILE_MIN_TRADES = 15      # minimaal N trades voor betrouwbare data
    coin_rsi_profiles: dict = {}      # sym → rsi_threshold
    last_profile_refresh = 0.0

    def _refresh_coin_profiles() -> dict:
        """Bereken per-coin RSI threshold op basis van historische win rate.
        Coins met lage win rate krijgen een lagere (conservatievere) drempel.
        Formule: threshold = globaal * (win_rate / 50) — geclipped op [18, 40].
        """
        try:
            from db_compat import get_conn, adapt_query
            _ov = _get_config_overrides()
            _global_threshold = float(_ov.get("rsi_buy_threshold", RSI_BUY_THRESHOLD))
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(adapt_query("""
                SELECT symbol,
                       COUNT(*) as n,
                       AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100 as win_rate
                FROM signal_performance
                WHERE pnl_1h_pct IS NOT NULL
                  AND signal IN ('BUY', 'MOMENTUM', 'BREAKOUT_BULL', 'PERFECT_DAY')
                GROUP BY symbol
                HAVING COUNT(*) >= ?
            """), (COIN_PROFILE_MIN_TRADES,))
            rows = cur.fetchall()
            conn.close()
            profiles = {}
            for row in rows:
                sym, n, win_rate = row[0], row[1], float(row[2])
                adjusted = _global_threshold * (win_rate / 50.0)
                profiles[sym] = round(max(18.0, min(40.0, adjusted)), 1)
                if abs(profiles[sym] - _global_threshold) > 2:
                    print(f"[profiel] {sym}: RSI drempel={profiles[sym]} "
                          f"(win_rate={win_rate:.1f}%, n={n})")
            return profiles
        except Exception as e:
            print(f"[profiel] DB fout: {e}")
            return {}

    def _refresh_signal_blacklist() -> set:
        """Haal signal/coin combos op met structureel slechte PnL uit de DB."""
        try:
            from db_compat import get_conn, adapt_query
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(adapt_query("""
                SELECT symbol, signal, COUNT(*) as n, AVG(pnl_1h_pct) as avg_pnl
                FROM signal_performance
                WHERE pnl_1h_pct IS NOT NULL
                GROUP BY symbol, signal
                HAVING COUNT(*) >= ? AND AVG(pnl_1h_pct) < ?
            """), (SIGNAL_BLACKLIST_MIN_TRADES, SIGNAL_BLACKLIST_PNL_THRESHOLD))
            rows = cur.fetchall()
            conn.close()
            result = set()
            for row in rows:
                sym, sig = row[0], row[1]
                result.add((sym, sig))
                print(f"[blacklist] {sym} {sig} geblokkeerd (avg_pnl_1h={float(row[3]):.3f}%, n={row[2]})")
            return result
        except Exception as e:
            print(f"[blacklist] DB fout: {e}")
            return set()

    # BTC Cascade handler — logt event naar DB én DataLogger
    def _on_cascade(coins, btc_drop_pct, urgentie, btc_price=0):
        syms = [c["symbol"] for c in coins]
        print(f"[cascade] BTC drop {btc_drop_pct:.1f}% → CASCADE SHORT: {syms} | urgentie={urgentie}")
        log_event(db_path, source="cascade", level="warning",
                  title=f"BTC Cascade SHORT gedetecteerd ({btc_drop_pct:.1f}%)",
                  payload={"coins": syms, "urgentie": urgentie, "btc_price": btc_price})
        data_logger.log_market_event(
            "BTC_CASCADE", symbol="BTCUSDT", severity=urgentie,
            value=round(btc_drop_pct, 2),
            description=f"BTC drop {btc_drop_pct:.2f}% → cascade naar {syms}",
            payload={"coins": coins, "btc_price": btc_price},
        )

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

        # Coin profielen — periodiek verversen
        if now - last_profile_refresh > COIN_PROFILE_REFRESH:
            coin_rsi_profiles = _refresh_coin_profiles()
            last_profile_refresh = now

        # Signal blacklist — periodiek verversen
        if now - last_blacklist_refresh > SIGNAL_BLACKLIST_REFRESH:
            signal_blacklist = _refresh_signal_blacklist()
            last_blacklist_refresh = now

        # BTC filter — altijd BTC indicatoren ophalen ongeacht tracked_coins
        try:
            _btc_ind = calc_indicators("BTCUSDT", "1h") or {}
            _btc_mtf = calculate_multi("BTCUSDT", "HOLD", _btc_ind.get("rsi") or 50) or {}
            btc_state["ema_bull"] = _btc_mtf.get("tf_detail", {}).get("1h", {}).get("ema_bull")
            btc_state["rsi"] = _btc_ind.get("rsi")
        except Exception as _e:
            print(f"[btc-filter] BTC indicator fout: {_e}")

        # BTC EMA200 check (4h via indicator_engine) — elke 15 min
        if now - last_ema200_check > BTC_EMA200_REFRESH:
            btc_state["above_ema200"] = _get_btc_ema200_ok()
            last_ema200_check = now
            if not btc_state["above_ema200"]:
                print("[btc-ema200] BTC onder EMA200 (4h) — alle long entries geblokkeerd")

        coin_states = []
        for coin in tracked_coins:
            sym   = coin["symbol"]
            price = BinanceFeed(sym).get_last_price() or coin.get("price", 0.0)
            vol   = coin.get("volume_usdt", 0.0)

            # STAP 17: Exchange Intel (gewogen consensus)
            ex_consensus = 0.0
            ex_coinbase_lead = False
            if EXCHANGE_INTEL_ENABLED:
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
            mtf = calculate_multi(sym, signal, ind.get("rsi") or 50) or {}
            if mtf.get("downgraded") and signal not in ("HOLD", "DANGER"):
                signal = "HOLD"
                active_signals.append("⚠️MTF-Down")
            elif mtf.get("upgraded") and signal not in ("DANGER",):
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
            _overrides = _get_config_overrides()
            _rsi_global = _overrides.get("rsi_buy_threshold", RSI_BUY_THRESHOLD)
            _rsi_limit = coin_rsi_profiles.get(sym, _rsi_global)
            _current_rsi = ind.get("rsi")
            _rsi_ok = _current_rsi is not None and _current_rsi < _rsi_limit

            # Skip coins — coins die we bewust overslaan
            _ov_skip = _get_config_overrides()
            _skip_coins = set(_ov_skip.get("skip_coins", []))
            if sym.replace("-", "") in _skip_coins or sym in _skip_coins:
                print(f"[skip] {sym} in skip_coins — overgeslagen")
                continue

            # BTC EMA200 filter — geen longs als BTC onder EMA200 (4h)
            _btc_ema200_blocked = (not btc_state["above_ema200"]
                                   and sym not in BTC_FILTER_EXEMPT
                                   and signal in ("BUY", "BREAKOUT_BULL", "MOMENTUM", "PERFECT_DAY"))
            if _btc_ema200_blocked:
                print(f"[btc-ema200] {sym} {signal} geblokkeerd — BTC onder EMA200 (bear market)")

            # BTC EMA21/55 filter — blokkeer altcoin BUY/BREAKOUT_BULL als BTC bearish
            _btc_bearish = (btc_state["ema_bull"] is False
                            and (btc_state["rsi"] or 50) < BTC_RSI_THRESHOLD)
            _btc_blocked = ((_btc_bearish or _btc_ema200_blocked)
                            and sym not in BTC_FILTER_EXEMPT
                            and signal in ("BUY", "BREAKOUT_BULL", "MOMENTUM"))
            if _btc_blocked and not _btc_ema200_blocked:
                print(f"[btc-filter] {sym} {signal} geblokkeerd — BTC bearish "
                      f"(ema_bull={btc_state['ema_bull']}, RSI={btc_state['rsi']:.1f})")

            # Signal blacklist — blokkeer (coin, signal) combos met structureel slechte PnL
            _blacklisted = (sym, signal) in signal_blacklist
            if _blacklisted:
                print(f"[blacklist] {sym} {signal} geblokkeerd (slechte historische PnL)")

            # Pattern engine filter — 1h + 4h confirmatie + confidence threshold
            _pattern_blocked = False
            _ov_now = _get_config_overrides()
            _min_confidence = float(_ov_now.get("pattern_min_confidence", 0.0))
            if signal in ("BUY", "BREAKOUT_BULL", "MOMENTUM", "PERFECT_DAY") and not _btc_blocked and not _blacklisted:
                _pat1h = _get_pattern_signal(sym, "1h")
                _pat4h = _get_pattern_signal(sym, "4h")
                _sig1h = _pat1h.get("signaal", "HOLD")
                _sig4h = _pat4h.get("signaal", "HOLD")
                _conf1h = float(_pat1h.get("confidence") or 0)
                _conf4h = float(_pat4h.get("confidence") or 0)

                if _sig1h == "AVOID":
                    _pattern_blocked = True
                    print(f"[pattern] {sym} geblokkeerd — 1h AVOID "
                          f"(win_rate={_pat1h.get('win_rate')}%, pnl={_pat1h.get('avg_pnl_1h')}%)")
                elif _sig4h == "AVOID":
                    _pattern_blocked = True
                    print(f"[pattern] {sym} geblokkeerd — 4h AVOID "
                          f"(win_rate={_pat4h.get('win_rate')}%, pnl={_pat4h.get('avg_pnl_1h')}%)")
                elif _min_confidence > 0 and _conf1h < _min_confidence:
                    _pattern_blocked = True
                    print(f"[pattern] {sym} geblokkeerd — 1h confidence {_conf1h:.2f} < min {_min_confidence:.2f}")
                else:
                    _both_buy = _sig1h == "BUY" and _sig4h == "BUY"
                    print(f"[pattern] {sym} 1h={_sig1h}(c={_conf1h:.2f}) "
                          f"4h={_sig4h}(c={_conf4h:.2f})"
                          + (" — DUBBELE BEVESTIGING" if _both_buy else ""))

            # RSI chop zone filter — block entries in RSI 30-55 neutrale zone
            # Uitzondering: BREAKOUT_BULL en PERFECT_DAY mogen bij RSI 55-65
            _rsi_chop_max = float(_ov_now.get("rsi_chop_max", 55.0))
            _chop_blocked = False
            if signal == "BUY" and _current_rsi is not None:
                _rsi_thresh = float(_ov_now.get("rsi_buy_threshold", RSI_BUY_THRESHOLD))
                if _rsi_thresh < _current_rsi < _rsi_chop_max:
                    _chop_blocked = True
                    print(f"[chop] {sym} RSI={_current_rsi:.1f} in chop zone ({_rsi_thresh:.0f}-{_rsi_chop_max:.0f}) — geblokkeerd")

            # Max posities — blokkeer als max open posities bereikt
            _max_pos = int(_ov_now.get("max_positions", 4))
            _open_pos = count_open_demo_positions()
            _max_blocked = _open_pos >= _max_pos
            if _max_blocked:
                print(f"[max-pos] {sym}: {_open_pos}/{_max_pos} open posities — geblokkeerd")

            _buy_blocked = _btc_blocked or _blacklisted or _pattern_blocked or _chop_blocked or _max_blocked

            if signal in ("PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM", "BUY") and price \
               and (now - last_signal_log.get(sig_key, 0)) > SIGNAL_LOG_COOLDOWN:
                log_signal_entry(db_path, symbol=sym, signal=signal,
                                 entry_price=price, active_signals=active_signals)
                log_market_context(db_path, symbol=sym, signal=signal, entry_price=price,
                                   rsi_5m=ind.get("rsi"), tf_confirm_score=mtf.get("confirm_score"),
                                   tf_bias=mtf.get("tf_bias"), tf_detail=mtf.get("tf_detail", {}))
                if _rsi_ok and not _buy_blocked:
                    demo_virtual_buy(db_path, symbol=sym, price=price, signal=signal)
                    # Sla fingerprint op voor live feedback na 1h
                    _fp = _pat1h.get("fingerprint") if "_pat1h" in dir() else {}
                    if _fp:
                        _pending_feedback[sym] = {
                            "fingerprint": _fp, "entry_price": price,
                            "buy_time": now, "interval": "1h",
                        }
                elif not _rsi_ok:
                    print(f"[apex] RSI filter: {sym} RSI={_current_rsi:.1f} >= {_rsi_limit} — demo koop geblokkeerd")
                last_signal_log[sig_key] = now

            # Order logica — IJZEREN WET: geen koop als crash score te hoog of RSI te hoog
            order_signal = signal in ("PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM", "BUY")
            if order_signal and price and not flash_triggered and not ind.get("danger") \
               and safe_to_buy and _rsi_ok and not _buy_blocked \
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

            # ── Live pattern feedback — stuur resultaat terug na 1h ──────
            if sym in _pending_feedback and price:
                _fb = _pending_feedback[sym]
                _age = now - _fb["buy_time"]
                if _age >= 3600:
                    _pnl = (price / _fb["entry_price"] - 1) * 100
                    _send_pattern_feedback(sym, _fb["fingerprint"], _pnl, _fb["interval"])
                    del _pending_feedback[sym]

            # ── DataLogger: historische opslag voor AI-geheugen ──────────
            data_logger.maybe_log_snapshot(
                symbol=sym, price=price,
                rsi=ind.get("rsi"), volume_usdt=vol,
                signal=signal, change_pct=coin.get("change_pct", 0.0),
                atr=ind.get("atr"), tf_bias=mtf.get("tf_bias"),
            )
            data_logger.maybe_log_crash_score(
                symbol=sym, score=crash_score,
            )
            if EXCHANGE_INTEL_ENABLED and ex_consensus:
                data_logger.maybe_log_exchange_consensus(
                    symbol=sym, consensus=ex_consensus,
                    prices={},  # exchange_intel cache niet direct toegankelijk
                    coinbase_lead=ex_coinbase_lead,
                )

            # Log marktgebeurtenissen meteen
            if flash_triggered:
                data_logger.log_market_event(
                    "FLASH_CRASH", symbol=sym, severity="HIGH",
                    value=price, description=f"Flash crash gedetecteerd op {sym}",
                )
            if crash_score >= 80 and last_pre_crash.get(sym, 0) < 80:
                data_logger.log_market_event(
                    "PRE_CRASH_CRITICAL", symbol=sym, severity="CRITICAL",
                    value=crash_score,
                    description=f"Pre-crash score KRITIEK: {crash_score:.0f}/100",
                )
            elif crash_score >= 60 and last_pre_crash.get(sym, 0) < 60:
                data_logger.log_market_event(
                    "PRE_CRASH_WARNING", symbol=sym, severity="HIGH",
                    value=crash_score,
                    description=f"Pre-crash score waarschuwing: {crash_score:.0f}/100",
                )
            if ex_coinbase_lead:
                data_logger.log_market_event(
                    "COINBASE_LEAD", symbol=sym, severity="MEDIUM",
                    value=round(ex_consensus, 4),
                    description=f"Coinbase wijkt significant af van consensus",
                )

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

        # Bewaar config_overrides van control_api (proposals) bij elke schrijfcyclus
        _existing_overrides = None
        try:
            with open("/var/apex/bot_state.json", "r", encoding="utf-8") as _f:
                _existing_overrides = json.load(_f).get("config_overrides")
        except Exception:
            pass

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
            "config_overrides": _existing_overrides,
        })
        time.sleep(10)

if __name__ == "__main__":
    main()
