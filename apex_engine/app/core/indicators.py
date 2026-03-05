"""
Indicator Engine — Alle strategieën uit xlmtradingstool + dachboardxrp
RSI-MACD Bounce | Bollinger Squeeze | Golden Cross | StochRSI | ADX | Perfect Storm
"""
import requests
import numpy as np
import pandas as pd
import talib
from typing import Dict, Optional

TIMEFRAME_WEIGHTS = {"1h": 0.5, "4h": 0.35, "1d": 0.15}

def fetch_ohlcv(symbol: str, interval: str = "5m", limit: int = 300) -> Optional[Dict[str, np.ndarray]]:
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        return {
            "open":   np.array([float(c[1]) for c in data]),
            "high":   np.array([float(c[2]) for c in data]),
            "low":    np.array([float(c[3]) for c in data]),
            "close":  np.array([float(c[4]) for c in data]),
            "volume": np.array([float(c[5]) for c in data]),
        }
    except Exception as e:
        print(f"[indicators] OHLCV fout {symbol}: {e}")
        return None

def calculate_multi(symbol: str, base_signal: str, base_rsi: float) -> Dict:
    """
    Multi-timeframe bevestiging: controleer 1h, 4h, 1d trend.
    Geeft terug:
      confirm_score  0-100  (hoe sterk hogere TF de entry bevestigen)
      tf_bias        'bullish' | 'bearish' | 'neutral'
      tf_detail      dict per timeframe
    """
    detail = {}
    bull_score = 0.0
    total_weight = 0.0

    for tf, weight in TIMEFRAME_WEIGHTS.items():
        ohlcv = fetch_ohlcv(symbol, tf, 120)
        if ohlcv is None or len(ohlcv["close"]) < 50:
            continue
        c = ohlcv["close"]
        h = ohlcv["high"]
        l = ohlcv["low"]
        try:
            rsi_tf   = talib.RSI(c, 14)[-1]
            ema21_tf = talib.EMA(c, 21)[-1]
            ema55_tf = talib.EMA(c, 55)[-1]
            macd_, _, hist_tf = talib.MACD(c, 12, 26, 9)
            mh = hist_tf[-1]
        except Exception:
            continue
        if any(np.isnan(x) for x in [rsi_tf, ema21_tf, ema55_tf, mh]):
            continue

        is_bull = (ema21_tf > ema55_tf) and (mh > 0) and (rsi_tf < 70)
        is_bear = (ema21_tf < ema55_tf) and (mh < 0) and (rsi_tf > 30)

        detail[tf] = {
            "rsi":  round(float(rsi_tf), 1),
            "ema_bull": bool(ema21_tf > ema55_tf),
            "macd_bull": bool(mh > 0),
            "bias": "bull" if is_bull else ("bear" if is_bear else "neutral"),
        }
        if is_bull:
            bull_score += weight
        elif not is_bear:
            bull_score += weight * 0.5  # neutraal = half punten
        total_weight += weight

    if total_weight == 0:
        return {"confirm_score": 50, "tf_bias": "neutral", "tf_detail": {}}

    score = round(bull_score / total_weight * 100)
    bias = "bullish" if score >= 60 else ("bearish" if score <= 40 else "neutral")

    # Downgrade BUY-signaal als hogere TF bearish is
    downgraded = False
    if base_signal in ("PERFECT_DAY", "BREAKOUT_BULL", "MOMENTUM", "BUY") and bias == "bearish":
        downgraded = True
    # Upgrade als hogere TF super bullish
    upgraded = False
    if base_signal == "BUY" and bias == "bullish" and score >= 75 and base_rsi < 40:
        upgraded = True

    return {
        "confirm_score": score,
        "tf_bias":       bias,
        "tf_detail":     detail,
        "downgraded":    downgraded,
        "upgraded":      upgraded,
    }


def calculate(symbol: str, interval: str = "5m") -> Optional[Dict]:
    ohlcv = fetch_ohlcv(symbol, interval)
    if ohlcv is None or len(ohlcv["close"]) < 60:
        return None

    o = ohlcv["open"]
    h = ohlcv["high"]
    l = ohlcv["low"]
    c = ohlcv["close"]
    v = ohlcv["volume"]

    # === MOMENTUM ===
    rsi14   = talib.RSI(c, 14)
    rsi21   = talib.RSI(c, 21)
    macd, macd_sig, macd_hist = talib.MACD(c, 12, 26, 9)
    stoch_k, stoch_d = talib.STOCH(h, l, c, fastk_period=14, slowk_period=3, slowd_period=3)
    stochrsi_k, stochrsi_d = talib.STOCHRSI(c, timeperiod=14, fastk_period=3, fastd_period=3)
    williams_r = talib.WILLR(h, l, c, 14)

    # === TREND ===
    ema9   = talib.EMA(c, 9)
    ema21  = talib.EMA(c, 21)
    ema55  = talib.EMA(c, 55)
    ema200 = talib.EMA(c, 200)
    adx    = talib.ADX(h, l, c, 14)
    plus_di= talib.PLUS_DI(h, l, c, 14)
    minus_di=talib.MINUS_DI(h, l, c, 14)
    sar    = talib.SAR(h, l)

    # === VOLATILITY ===
    bb_upper, bb_mid, bb_lower = talib.BBANDS(c, 20, 2, 2)
    bb_width = (bb_upper - bb_lower) / bb_mid * 100
    atr    = talib.ATR(h, l, c, 14)

    # === VOLUME ===
    obv    = talib.OBV(c, v)
    vol_sma= talib.SMA(v, 20)

    # === XRP-SPECIFIEKE BEREKENINGEN (161125xrp) ===
    # Wick-to-ATR ratio (grote wicks = onstabiel, vermijden)
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l
    max_wick   = np.maximum(upper_wick, lower_wick)
    atr_vals   = talib.ATR(h, l, c, 14)
    wick_to_atr_arr = np.where(atr_vals > 0, max_wick / atr_vals, 0)

    # Round number proximity voor XRP (bps afstand tot dichtstbijzijnde round number)
    xrp_round_nums = [5.0, 4.0, 3.0, 2.5, 2.0, 1.5, 1.0, 0.90, 0.80, 0.75, 0.70, 0.60, 0.50, 0.40, 0.30, 0.25]
    def round_num_dist_bps(price):
        if not price or price <= 0:
            return 10000
        dists = [abs(price - rn) / rn for rn in xrp_round_nums]
        return min(dists) * 10000

    # Laatste waarden
    def val(arr): return float(arr[-1]) if arr is not None and not np.isnan(arr[-1]) else None
    def val2(arr): return float(arr[-2]) if arr is not None and len(arr) > 1 and not np.isnan(arr[-2]) else None

    price     = val(c)
    _rsi      = val(rsi14)
    _rsi21    = val(rsi21)
    _macd_h   = val(macd_hist)
    _macd_h2  = val2(macd_hist)  # vorige candle
    _macd     = val(macd)
    _macd_s   = val(macd_sig)
    _sk       = val(stoch_k)
    _sd       = val(stoch_d)
    _srsi_k   = val(stochrsi_k)
    _srsi_d   = val(stochrsi_d)
    _wr       = val(williams_r)
    _ema9     = val(ema9)
    _ema21    = val(ema21)
    _ema55    = val(ema55)
    _ema200   = val(ema200)
    _adx      = val(adx)
    _plus_di  = val(plus_di)
    _minus_di = val(minus_di)
    _sar      = val(sar)
    _bb_upper = val(bb_upper)
    _bb_lower = val(bb_lower)
    _bb_w     = val(bb_width)
    _atr      = val(atr)
    _obv      = val(obv)
    _vol_sma  = val(vol_sma)
    _vol          = float(v[-1])
    _wick_to_atr  = float(wick_to_atr_arr[-1]) if not np.isnan(wick_to_atr_arr[-1]) else 0.0
    _round_dist   = round_num_dist_bps(price if price else 0)
    # XRP wick filter: grote wick → entry vermijden (161125xrp threshold: 0.6)
    _wick_ok      = _wick_to_atr < 0.6

    if None in (price, _rsi, _macd_h):
        return None

    # ── Strategie 1: RSI-MACD Bounce (161125xrp: tighter RSI 24 + wick filter) ──
    rsi_macd_long  = _rsi < 32 and _macd_h is not None and _macd_h > 0 and _macd is not None and _macd_s is not None and _macd > _macd_s and _wick_ok
    rsi_macd_short = _rsi > 68 and _macd_h is not None and _macd_h < 0 and _macd is not None and _macd_s is not None and _macd < _macd_s and _wick_ok
    rsi_macd_conf  = min(95, max(50, abs(50 - _rsi) * 1.5 + abs(_macd_h or 0) * 500))

    # ── Strategie 2: Bollinger Squeeze Explosion ──
    squeeze        = _bb_w is not None and _bb_w < 2.5
    bb_long        = squeeze and price is not None and _bb_upper is not None and price > _bb_upper
    bb_short       = squeeze and price is not None and _bb_lower is not None and price < _bb_lower
    bb_conf        = min(95, max(50, (2.5 - (_bb_w or 2.5)) * 30)) if squeeze else 50

    # ── Strategie 3: Golden Cross Momentum ──
    golden_cross   = _ema21 and _ema55 and _ema200 and _ema21 > _ema55 > _ema200
    death_cross    = _ema21 and _ema55 and _ema200 and _ema21 < _ema55 < _ema200
    gc_strength    = abs((_ema21 - _ema55) / _ema55 * 100) if _ema21 and _ema55 else 0
    gc_conf        = min(95, max(50, gc_strength * 40))

    # ── Strategie 4: Stochastic RSI Divergence ──
    srsi_long      = _srsi_k is not None and _srsi_d is not None and _srsi_k < 20 and _srsi_k > _srsi_d and _rsi < 45
    srsi_short     = _srsi_k is not None and _srsi_d is not None and _srsi_k > 80 and _srsi_k < _srsi_d and _rsi > 55
    srsi_conf      = min(95, max(50, abs(50 - (_srsi_k or 50)) + abs(50 - _rsi)))

    # ── Strategie 5: ADX Momentum Breakout ──
    strong_trend   = _adx is not None and _adx > 25
    adx_long       = strong_trend and _plus_di is not None and _minus_di is not None and _plus_di > _minus_di
    adx_short      = strong_trend and _plus_di is not None and _minus_di is not None and _minus_di > _plus_di
    adx_conf       = min(95, max(50, (_adx or 0) * 2)) if strong_trend else 50

    # ── Perfect Storm (uit dachboardxrp) ──
    # Alle bullish condities tegelijk actief
    perfect_day  = (
        rsi_macd_long and
        (bb_long or squeeze) and
        (golden_cross or (_ema9 and _ema21 and _ema9 > _ema21)) and
        adx_long
    )

    # ── Breakout Bull ──
    breakout_bull  = (
        price is not None and _bb_upper is not None and price > _bb_upper and
        _rsi > 50 and
        _vol > (_vol_sma or 0) * 1.5
    )

    # ── Danger Reversal (exit signaal) ──
    danger_reversal = (
        _rsi is not None and _rsi > 72 and
        _macd_h is not None and _macd_h < 0 and
        (_sar and price and price < _sar)
    )

    # ── Danger Breakdown ──
    danger_breakdown = (
        price is not None and _bb_lower is not None and price < _bb_lower and
        _rsi is not None and _rsi < 35 and
        _adx is not None and _adx > 20
    )

    # ── Momentum Continuation ──
    momentum_cont  = (
        golden_cross and
        _rsi is not None and 50 < _rsi < 65 and
        _macd_h is not None and _macd_h > 0 and
        adx_long
    )

    # ── Hoofdsignaal (prioriteit volgorde) ──
    if perfect_day:
        signal = "PERFECT_DAY"
    elif breakout_bull:
        signal = "BREAKOUT_BULL"
    elif momentum_cont:
        signal = "MOMENTUM"
    elif danger_reversal or danger_breakdown:
        signal = "DANGER"
    elif rsi_macd_long or bb_long or golden_cross or srsi_long or adx_long:
        signal = "BUY"
    elif rsi_macd_short or bb_short or death_cross or srsi_short or adx_short:
        signal = "SELL"
    else:
        signal = "HOLD"

    # Actieve strategieën
    active = []
    if rsi_macd_long:   active.append("RSI-MACD")
    if bb_long:         active.append("BB-Squeeze")
    if golden_cross:    active.append("GoldenCross")
    if srsi_long:       active.append("StochRSI")
    if adx_long:        active.append("ADX")
    if perfect_day:   active.append("⭐PerfectDay")
    if breakout_bull:   active.append("Breakout")
    if danger_reversal: active.append("⚠️DangerRev")
    if danger_breakdown:active.append("⚠️DangerBD")

    return {
        "symbol":         symbol,
        "price":          price,
        "signal":         signal,
        "active_signals": active,
        # Momentum
        "rsi":            round(_rsi, 2)    if _rsi    else None,
        "rsi21":          round(_rsi21, 2)  if _rsi21  else None,
        "macd_hist":      round(_macd_h, 6) if _macd_h else None,
        "stoch_k":        round(_sk, 2)     if _sk     else None,
        "williams_r":     round(_wr, 2)     if _wr     else None,
        # Trend
        "ema21":          round(_ema21, 4)  if _ema21  else None,
        "ema55":          round(_ema55, 4)  if _ema55  else None,
        "adx":            round(_adx, 2)    if _adx    else None,
        "plus_di":        round(_plus_di,2) if _plus_di else None,
        "minus_di":       round(_minus_di,2)if _minus_di else None,
        # Volatility
        "bb_upper":       round(_bb_upper,4)if _bb_upper else None,
        "bb_lower":       round(_bb_lower,4)if _bb_lower else None,
        "bb_width":       round(_bb_w, 3)   if _bb_w   else None,
        "atr":            round(_atr, 6)    if _atr    else None,
        # Flags
        "perfect_day":  perfect_day,
        "breakout_bull":  breakout_bull,
        "momentum_cont":  momentum_cont,
        "danger":         danger_reversal or danger_breakdown,
        "golden_cross":   golden_cross,
        "squeeze":        squeeze,
        # XRP-specifieke filters (161125xrp)
        "wick_to_atr":    round(_wick_to_atr, 3),
        "wick_ok":        _wick_ok,
        "round_num_dist": round(_round_dist, 1),
    }
