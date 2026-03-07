# Data & Analysis Architecture — OpenClaw Apex Trading Platform

**Version:** 1.0 (2026-03-07)
**Purpose:** Technical overview of all data and analysis layers for architecture review and AI analysis.

---

## 1. Database Overview

The platform uses two databases in parallel:

| Database | Location | Used by |
|----------|----------|---------|
| **PostgreSQL 16** | `postgres` container, port 5432, database `apex` | indicator_engine, apex_engine, control_api, kimi_pattern_agent, jojo_analytics |
| **SQLite** (`apex.db`) | Docker volume `/var/apex/apex.db` | apex_engine (live trading data, signal_context, verdict_log) |

---

### 1.1 ohlcv_data (PostgreSQL)

| Property | Value |
|----------|-------|
| **Records** | 1,390,981 |
| **Coins** | 40 |
| **Timeframes** | 1h, 4h |
| **Period** | 2017-08-17 → present (live updated) |
| **Source** | Binance API — `indicator_engine` import |

**Columns:** `symbol, interval, ts, open, high, low, close, volume`

**Purpose:** Raw OHLCV price data. Basis for all indicator calculations.

**Population:** `POST /import` on indicator_engine fetches historical candles from Binance. Then incremental update every 60 minutes via APScheduler.

---

### 1.2 indicators_data (PostgreSQL)

| Property | Value |
|----------|-------|
| **Records** | 1,350,937 |
| **Coins** | 40 |
| **Timeframes** | 1h (988,476 rows), 4h (362,461 rows) |
| **Period** | 2017-08-26 → present |
| **Source** | Calculated by indicator_engine from ohlcv_data |

**Columns:**
```
id, symbol, interval, ts,
rsi, rsi_zone,
macd_hist,
bb_width, bb_position,
ema21, ema55, ema200, ema_bull,
adx, stoch_rsi_k, stoch_rsi_d,
atr, volume_ratio
```

**Indicators:**
| Indicator | Period/Setting |
|-----------|---------------|
| RSI | 14 periods |
| RSI zone | oversold (<35) / mid-low / mid-high / overbought (>65) |
| MACD histogram | 12/26/9 EMA |
| Bollinger Bands | 20 periods, 2 std — width + position (low/mid/high) |
| EMA21 / EMA55 / EMA200 | Exponential Moving Average |
| ema_bull | boolean: ema21 > ema55 > ema200 |
| ADX | 14 periods — trend strength |
| StochRSI K/D | 14/3/3 |
| ATR | 14 periods — volatility |
| volume_ratio | volume / average volume (20 periods) |

**Purpose:** Pre-calculated indicator snapshots for each candle per coin. Enables fast lookups without real-time recalculation.

**Population:** After OHLCV import, indicator_engine calculates all indicators via TA-Lib and stores them.

---

### 1.3 historical_context (PostgreSQL)

| Property | Value |
|----------|-------|
| **Records** | ~500,000+ |
| **Coins** | 17 |
| **Period** | 2022 → 2026 (4 years) |
| **Source** | apex_engine backtesting on own signal logic |

**Columns:**
```
id, run_ts, symbol, interval, months,
candle_ts, signal, active_signals,
entry_price,
price_1h, price_4h, price_24h,
pnl_1h_pct, pnl_4h_pct, pnl_24h_pct
```

**Signal distribution:** BUY, BREAKOUT_BULL, MOMENTUM

**Purpose:** Historical backtest results — per signal: entry price + PnL at 1h/4h/24h after entry. Used by the P1 Setup Scoring system to calculate verdicts (STERK/TOESTAAN/TOESTAAN_ZWAK/SKIP).

---

### 1.4 testbot_trades (PostgreSQL)

Paper trading bot trade log.

**Columns:**
```
id, symbol, signal, setup_score, verdict,
entry_price, stake_usd, fee_rate,
tp_price, sl_price,
close_price, close_reason,
pnl_pct, gross_pnl_usd, fee_usd, net_pnl_usd,
opened_at, closed_at, duration_min,
status,
price_15m, price_1h, price_2h,
pnl_15m_pct, pnl_1h_pct, pnl_2h_pct
```

**Purpose:** Tracks all paper trades opened by the testbot (STERK signals only). Used for STERK Quality analysis and chart markers.

---

### 1.5 crash_score_log (PostgreSQL)

| Property | Value |
|----------|-------|
| **Purpose** | Market crash probability score over time |
| **Source** | apex_engine crash detection algorithm |

**Columns:** `id, ts, symbol, score, factors`

---

### 1.6 SQLite tables (apex.db)

| Table | Contents |
|-------|----------|
| `signal_context` | Latest live signals from apex_engine |
| `verdict_log` | Legacy signal verdict log (old system) |
| `otp_codes` | Temporary OTP codes for authentication (10 min expiry) |
| `sessions` | Active user sessions (24 hour TTL) |
| `proposals_v2` | Gatekeeper proposals (pending/confirmed/rejected) |

---

## 2. Data Flow

### 2.1 OHLCV Import Pipeline

```
Binance API
    │ GET /api/v3/klines
    ▼
indicator_engine /import
    │ pandas + TA-Lib
    ▼
ohlcv_data (PostgreSQL)
    │
    ▼
indicators_data (PostgreSQL)
    │
    ▼
historical_context (PostgreSQL)  ← backtesting
    │
    ▼
P1 Setup Scoring (control_api)
    │
    ▼
/setup/scan, /live/signals, /setup/chart-markers
```

### 2.2 Live Signal Detection

```
indicators_data (last row per coin)
    │
    ▼
_detect_signal() in control_api/server.py
    │
    ├── BREAKOUT_BULL: bb_position='above_upper' + rsi>50 + vol_ratio>1.5
    ├── MOMENTUM: ema_bull + rsi 50-65 + macd_hist>0 + adx>25
    └── BUY: rsi<32 + macd_hist>0, OR StochRSI oversold
    │
    ▼
_sj_query() + _sj_process_row()  ← P1 scoring lookup
    │
    ▼
/live/signals response
```

### 2.3 Testbot Trade Flow

```
/live/signals → active signal with STERK verdict
    │
    ▼
testbot.py (background thread in control_api)
    │ max 3 concurrent trades
    │ stake=$100, TP=+4.5%, SL=-2.0%, TIMEOUT=2h
    ▼
testbot_trades (PostgreSQL)
    │
    ├── /testbot/positions  ← open trades with live Binance price
    ├── /testbot/history    ← closed trades with PnL breakdown
    └── /testbot/markers/{symbol} ← chart overlay markers
```

---

## 3. Indicator Definitions

### RSI Zones
| Zone | RSI Range |
|------|-----------|
| oversold | < 35 |
| neutral_low | 35–50 |
| neutral_high | 50–65 |
| overbought | > 65 |

### BB Position
| Position | Meaning |
|----------|---------|
| below_lower | Price below lower Bollinger Band |
| lower_half | Price in lower half of BB range |
| upper_half | Price in upper half of BB range |
| above_upper | Price above upper Bollinger Band (breakout zone) |

### EMA Alignment
| Value | Meaning |
|-------|---------|
| `ema_bull = true` | EMA21 > EMA55 > EMA200 (uptrend alignment) |
| `ema_bull = false` | Not in uptrend alignment |

### ADX Strength
| ADX | Interpretation |
|-----|---------------|
| < 20 | Weak/no trend |
| 20–25 | Developing trend |
| > 25 | Strong trend |
| > 40 | Very strong trend |

---

## 4. P1 Setup Score Calculation

For each `(coin × signal_type)` combination:

```sql
SELECT
    signal,
    COUNT(*) as n,
    AVG(CASE WHEN pnl_1h_pct > 0 THEN 1.0 ELSE 0.0 END) * 100 as win_pct,
    AVG(pnl_1h_pct) as avg_pnl,
    MAX(candle_ts) as last_signal_ts
FROM historical_context
WHERE symbol = %s
GROUP BY signal
```

Score components:
- **Win rate (0-40 pts):** `win_pct / 100 * 40`
- **Avg PnL (0-30 pts):** capped at +0.5% → 30 pts
- **Sample size (0-15 pts):** `min(n/100, 1) * 15`, min 10 required
- **Regime (0-15 pts):** bonus if signal performs better in current BTC regime

Verdict thresholds:
- `STERK`: score >= 70 AND win% >= 55% AND avg_pnl >= 0.20% AND n >= 20
- `TOESTAAN`: score >= 50
- `TOESTAAN_ZWAK`: score >= 30
- `SKIP`: below thresholds or negative edge

---

## 5. Database Compatibility Layer

`db/db_compat.py` provides a unified interface for both SQLite and PostgreSQL:

```python
from db.db_compat import get_conn, adapt_query

conn = get_conn()  # returns PostgreSQL or SQLite connection
query = adapt_query("SELECT * WHERE ts > datetime('now', '-1 day')")
# → "SELECT * WHERE ts > NOW() - INTERVAL '1 day'"
```

`adapt_query()` conversions:
- `?` → `%s` (parameter placeholder)
- `datetime('now', ...)` → PostgreSQL `NOW() - INTERVAL ...`
- `ROUND(x, n)` → `ROUND(x::numeric, n)`
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`
