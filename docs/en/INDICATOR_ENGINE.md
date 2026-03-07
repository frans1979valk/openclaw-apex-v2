# INDICATOR_ENGINE.md — Apex Intelligence Engine

Version: 2026-03-06 | Service: `indicator_engine` | Port: 8099

---

## 1. Overview

The `indicator_engine` is a service that imports historical OHLCV data, calculates technical indicators, and uses **pattern matching** to determine whether a signal has historically been successful.

The engine adds an extra filter to `apex_engine` before every BUY decision: if the current market pattern has historically produced poor results, the BUY is blocked.

---

## 2. Architecture

```
Binance API
    │
    ▼
indicator_engine (port 8099)
    ├── ohlcv_data          (raw candles per coin + interval)
    ├── indicators_data     (calculated indicators per candle)
    └── pattern_results     (fingerprint + historical PnL per candle)
         │
         ▼ /signal/{symbol}
apex_engine
    └── _get_pattern_signal() → AVOID / HOLD / BUY
```

---

## 3. API Endpoints

### `GET /health`
Status + scheduler info.

```json
{
  "status": "ok",
  "service": "indicator_engine",
  "scheduled_jobs": [{"id": "incremental_update", "next_run": "..."}]
}
```

### `POST /import`
Start historical import in the background.

```json
// Request
{"months": 12, "intervals": ["1h", "4h"], "symbols": []}

// Response
{"ok": true, "message": "Import started for 17 coins"}
```

All 17 SAFE_COINS are imported by default. Empty `symbols` = all coins.

### `GET /indicators/{symbol}?interval=1h`
Most recent calculated indicators for a coin.

```json
{
  "ts": "2026-03-06 14:00:00+00:00",
  "rsi": 42.3,
  "macd_hist": 0.000123,
  "bb_width": 3.21,
  "bb_position": "lower_half",
  "ema21": 85432.1,
  "ema55": 84900.0,
  "ema200": 81200.0,
  "ema_bull": true,
  "adx": 28.4,
  "stoch_rsi_k": 34.2,
  "atr": 0.00312,
  "volume_ratio": 1.24,
  "rsi_zone": "neutral_low"
}
```

### `GET /signal/{symbol}?interval=1h`
Pattern-based signal analysis based on historical precedents.

```json
{
  "symbol": "BTCUSDT",
  "interval": "1h",
  "ts": "2026-03-06 14:00:00+00:00",
  "signal": "BUY",
  "confidence": 0.72,
  "precedents": 18,
  "avg_pnl_1h": 0.83,
  "avg_pnl_4h": 1.42,
  "win_rate": 72.2,
  "worst_case_1h": -0.31,
  "btc_trend": "bull",
  "fingerprint": {
    "rsi_zone": "neutral_low",
    "macd_direction": "bullish",
    "bb_position": "lower_half",
    "ema_alignment": "bull",
    "adx_strength": "strong"
  },
  "reason": "RSI neutral_low, bullish MACD, bull EMA — 18 precedents, 72.2% win rate"
}
```

**Signal values:**
| Signal | Meaning |
|--------|---------|
| `BUY` | Historically positive pattern (win_rate > 55%, avg_pnl_1h > 0.5%) |
| `HOLD` | Neutral — insufficient data or average pattern |
| `AVOID` | Historically negative (win_rate < 35% or avg_pnl_1h < -0.4%) |

### `GET /coverage`
Overview of available historical data per coin.

```json
[
  {"symbol": "BTCUSDT", "interval": "1h", "candles": 36006, "first_ts": "...", "last_ts": "..."},
  ...
]
```

### `GET /patterns/{symbol}?interval=1h`
Statistics per RSI zone and MACD direction for a coin.

```json
[
  {"rsi_zone": "oversold", "macd": "bullish", "n": 23, "avg_pnl_1h": 1.24, "win_rate": 69.6},
  {"rsi_zone": "neutral_low", "macd": "bullish", "n": 87, "avg_pnl_1h": 0.31, "win_rate": 52.9},
  ...
]
```

---

## 4. Pattern Fingerprint

Each candle gets a fingerprint of 5 dimensions:

| Dimension | Values |
|-----------|--------|
| `rsi_zone` | oversold / neutral_low / neutral_high / overbought |
| `macd_direction` | bullish / bearish |
| `bb_position` | below_lower / lower_half / upper_half / above_upper |
| `ema_alignment` | bull / bear |
| `btc_trend` | bull / bear / neutral |

For every unique combination, the following is computed from historical data:
- Number of prior occurrences (precedents)
- Average PnL after 1h and 4h
- Win rate (% positive after 1h)
- Worst case (lowest PnL after 1h)

Minimum 8 precedents required for a signal. Otherwise: `HOLD`.

---

## 5. Integration with apex_engine

`apex_engine` consults `indicator_engine` on every potential BUY via `_get_pattern_signal()`.

**Filter order (BUY only executed if all filters pass):**

```
Signal arrives (BUY / BREAKOUT_BULL / MOMENTUM / PERFECT_DAY)
    │
    ├── RSI per-coin profile      → RSI too high? BLOCK
    ├── BTC bearish filter        → BTC ema_bull=False and RSI<45? BLOCK
    ├── Signal blacklist          → (coin, signal) structurally bad? BLOCK
    └── Pattern engine            → AVOID? BLOCK | BUY? LOG CONFIRMATION
             │
             ▼
         Execute BUY
```

**Log output example:**
```
[pattern] XRPUSDT BUY blocked — pattern AVOID (win_rate=28%, pnl=-0.4%)
[pattern] SOLUSDT pattern confirms BUY (confidence=0.72, win_rate=63%, prec=18)
```

---

## 6. Automatic Updates

The scheduler runs an **incremental update** every 60 minutes:
- Fetches the latest 50 candles per coin per interval (Binance API)
- Stores new candles
- Recalculates indicators

The pattern database automatically grows as more market data becomes available.

---

## 7. Available Coins (SAFE_COINS)

BTCUSDT, ETHUSDT, SOLUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, DOTUSDT,
UNIUSDT, LTCUSDT, DOGEUSDT, XRPUSDT, BNBUSDT, ADAUSDT, ATOMUSDT,
ARBUSDT, APTUSDT, SEIUSDT

---

## 8. Database Tables

| Table | Contents |
|-------|----------|
| `ohlcv_data` | Raw candles: symbol, interval, ts, OHLCV |
| `indicators_data` | Calculated indicators per candle |
| `pattern_results` | Fingerprint + historical PnL per candle |

All tables are in the shared PostgreSQL database (`apex`).

---

## 9. Manual Usage

```bash
# Health check
curl http://localhost:8099/health

# Start historical import (12 months, all coins)
curl -X POST http://localhost:8099/import \
  -H "Content-Type: application/json" \
  -d '{"months": 12}'

# Get signal for BTCUSDT
curl http://localhost:8099/signal/BTCUSDT

# View data coverage
curl http://localhost:8099/coverage

# Pattern statistics for ETHUSDT
curl http://localhost:8099/patterns/ETHUSDT
```
