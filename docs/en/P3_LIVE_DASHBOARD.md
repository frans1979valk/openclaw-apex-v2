# P3 — Live Dashboard, Chart Markers & Signal Detection

Version: 2026-03-07 | Platform: OpenClaw Apex v2

---

## Overview

P3 adds three major layers on top of the P1/P2 foundation:

1. **Live Signals page** — current RSI/MACD/ADX per coin, active signal type, P1 verdict
2. **Chart markers** — 3 marker types on a single chart: Setup Intel moments + testbot entries + testbot exits
3. **Setup Intelligence improvements** — "Last signal" column, new API endpoints

---

## 1. Live Signals (`live_signals.html`)

### Purpose

A screen that shows: *which coins are giving a signal RIGHT NOW, what are the current indicator values, and what is the historical advice?*

This is fundamentally different from Setup Intelligence:
- **Setup Intelligence** = historical quality of a signal type (aggregate over 4 years)
- **Live Signals** = current market conditions + active signal + P1 verdict for that combination

### Signal Detection (`_detect_signal()` in server.py)

Uses the most recent row from `indicators_data` (interval=1h) per coin:

| Signal | Conditions |
|--------|------------|
| `BREAKOUT_BULL` | `bb_position = 'above_upper'` AND `rsi > 50` AND `volume_ratio > 1.5` |
| `MOMENTUM` | `ema_bull = True` AND `50 < rsi < 65` AND `macd_hist > 0` AND `adx > 25` |
| `BUY` | `rsi < 32` AND `macd_hist > 0`, OR StochRSI oversold (`sk < 20` AND `sk > sd` AND `rsi < 45`) |

### API endpoint

```http
GET /live/signals
```

Response per coin:
```json
{
  "symbol": "DOGEUSDT",
  "rsi": 26.5,
  "rsi_zone": "oversold",
  "macd_hist": -12.3,
  "adx": 38.9,
  "ema_bull": false,
  "bb_position": "lower_half",
  "volume_ratio": 0.86,
  "signal": "BUY",
  "verdict": "TOESTAAN_ZWAK",
  "setup_score": 47,
  "win_pct_1h": 49.6,
  "avg_1h": -0.009,
  "n": 5658
}
```

Sorted by: active signal first → verdict quality → lowest RSI.

### Frontend

- Auto-refresh every 60 seconds
- Filter: All / With signal / STERK+TOESTAAN only
- Click row → detail panel with plain-language interpretation
- Live prices via Binance public REST API (browser-side fetch)
- Status bar: BTC regime, number of active signals, number of STERK active

---

## 2. Chart Markers

### Three marker types on one chart

#### 2a. Setup Intel markers (historical)

**Endpoint:** `GET /setup/chart-markers/{symbol}?days=180`

Logic:
1. Calculate aggregate verdict per signal type for this symbol (same as `/setup/scan`)
2. Fetch all historical candles from `historical_context` for the last `days` days
3. Link each candle to the aggregate verdict of its signal type
4. Return only STERK / TOESTAAN / TOESTAAN_ZWAK (SKIP = noise, omitted)

Marker format:
```json
{
  "time": 1772643600,
  "verdict": "STERK",
  "signal": "BREAKOUT_BULL",
  "pnl_1h": 0.785,
  "win_pct": 83.3,
  "setup_score": 78,
  "n": 30
}
```

#### 2b. Testbot entry markers

**Endpoint:** `GET /testbot/markers/{symbol}`

Fetches all `testbot_trades` for the symbol, returns entries:
```json
{
  "trade_id": 1,
  "time": 1772912745,
  "entry_price": 67250.95,
  "signal": "BREAKOUT_BULL",
  "setup_score": 78,
  "stake_usd": 100.0,
  "status": "closed"
}
```

#### 2c. Testbot exit markers

Same endpoint, `exits` array:
```json
{
  "trade_id": 1,
  "time": 1772920000,
  "close_price": 70277.0,
  "close_reason": "TP",
  "pnl_pct": 4.49,
  "net_pnl_usd": 4.29,
  "fee_usd": 0.20,
  "duration_min": 122
}
```

### Visual distinction

| Marker | Color | Shape | Text |
|--------|-------|-------|------|
| Setup STERK | #3fb950 green | arrowUp belowBar | `STERK(BB) +0.79%` |
| Setup TOESTAAN | #58a6ff blue | arrowUp belowBar | `TOES(MOM) +0.42%` |
| Setup TOESTAAN_ZWAK | #d29922 yellow | arrowUp belowBar | `ZWAK(BUY) -0.01%` |
| Bot entry | #3fb950 green | arrowUp belowBar | `BOT s78` |
| Bot exit TP | #58a6ff blue | circle aboveBar | `TP +4.35$` |
| Bot exit SL | #f85149 red | square aboveBar | `SL -2.10$` |
| Bot exit TIMEOUT | #d29922 yellow | square aboveBar | `TMT +0.52$` |

### Timestamp snapping

LW Charts requires that `marker.time` exactly matches a candle open time. The `snapToCandle()` function floors each timestamp to the candle interval:

```js
function snapToCandle(unixSec) {
  const secs = {"1h": 3600, "4h": 14400, "15m": 900, "5m": 300}[_tf] || 3600;
  return Math.floor(unixSec / secs) * secs;
}
```

### Click handler

Priority on click: bot exit → bot entry → setup marker:
```js
_chartMain.subscribeClick(param => {
  const exit  = closest(_allBotExits,   "time");
  if (exit && exit.d <= tol)  { showBotExitPanel(exit.item);   return; }
  const entry = closest(_allBotEntries, "time");
  if (entry && entry.d <= tol) { showBotEntryPanel(entry.item); return; }
  const sv = closest(_allVerdicts, "time");
  if (sv && sv.d <= tol)      { showVerdictPanel(sv.item);      return; }
});
```

---

## 3. Setup Intelligence improvements

### "Last signal" column

Query extension in `/setup/scan`:
```sql
MAX(candle_ts) as last_signal_ts
```

`_sj_process_row()` calculates `last_signal_hours_ago` and returns it in the response.

Frontend `lastSignalFmt()`:
- `<= 6 hours` → **Active now** (green bold)
- `<= 24 hours` → `Xh ago` (green)
- `<= 72 hours` → `Xd ago` (yellow)
- `> 72 hours` → `Xd ago` (grey)

### Marker label with signal abbreviation

Markers on the chart now show the signal abbreviation so `STERK(BB)` vs `ZWAK(BUY)` is clear:
```js
const sigAbbr = {"BREAKOUT_BULL":"BB","MOMENTUM":"MOM","BUY":"BUY"}[v.signal];
const label = `${verdictLabel}(${sigAbbr})${pnlStr}`;
```

---

## Modified Files

| File | Change |
|------|--------|
| `control_api/app/server.py` | `_detect_signal()`, `GET /live/signals`, `GET /setup/chart-markers/{sym}`, `GET /testbot/markers/{sym}`, last_signal_ts in scan |
| `dashboard/live_signals.html` | New — complete live signals page |
| `dashboard/chart.html` | 3 marker types, snapToCandle, click handler, Setup Intel toggle |
| `dashboard/setup_intelligence.html` | "Last signal" column, `lastSignalFmt()` helper |
| `dashboard/index.html` | Live button added to navigation |
