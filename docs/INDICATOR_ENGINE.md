# INDICATOR_ENGINE.md — Apex Intelligence Engine

Versie: 2026-03-06 | Service: `indicator_engine` | Poort: 8099

---

## 1. Overzicht

De `indicator_engine` is een nieuwe service die historische OHLCV data importeert, technische indicatoren berekent en via **pattern matching** bepaalt of een signaal historisch succesvol is geweest.

De engine voegt een extra filter toe aan `apex_engine` vóór elke BUY-beslissing: als het huidige marktpatroon historisch slechte resultaten heeft, wordt de BUY geblokkeerd.

---

## 2. Architectuur

```
Binance API
    │
    ▼
indicator_engine (poort 8099)
    ├── ohlcv_data          (ruwe candles per coin + interval)
    ├── indicators_data     (berekende indicatoren per candle)
    └── pattern_results     (fingerprint + historische PnL per candle)
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
Start historische import in de achtergrond.

```json
// Request
{"months": 12, "intervals": ["1h", "4h"], "symbols": []}

// Response
{"ok": true, "message": "Import gestart voor 17 coins"}
```

Standaard worden alle 17 SAFE_COINS geïmporteerd. Leeg `symbols` = alle coins.

### `GET /indicators/{symbol}?interval=1h`
Meest recente berekende indicatoren voor een coin.

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
Pattern-based signaalanalyse op basis van historische precedenten.

```json
{
  "symbol": "BTCUSDT",
  "interval": "1h",
  "ts": "2026-03-06 14:00:00+00:00",
  "signaal": "BUY",
  "confidence": 0.72,
  "precedenten": 18,
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
  "reden": "RSI neutral_low, bullish MACD, bull EMA — 18 precedenten, 72.2% win rate"
}
```

**Signaal waarden:**
| Signaal | Betekenis |
|---------|-----------|
| `BUY` | Historisch positief patroon (win_rate > 55%, avg_pnl_1h > 0.5%) |
| `HOLD` | Neutraal — onvoldoende data of gemiddeld patroon |
| `AVOID` | Historisch negatief (win_rate < 35% of avg_pnl_1h < -0.4%) |

### `GET /coverage`
Overzicht beschikbare historische data per coin.

```json
[
  {"symbol": "BTCUSDT", "interval": "1h", "candles": 36006, "first_ts": "...", "last_ts": "..."},
  ...
]
```

### `GET /patterns/{symbol}?interval=1h`
Statistieken per RSI-zone en MACD-richting voor een coin.

```json
[
  {"rsi_zone": "oversold", "macd": "bullish", "n": 23, "avg_pnl_1h": 1.24, "win_rate": 69.6},
  {"rsi_zone": "neutral_low", "macd": "bullish", "n": 87, "avg_pnl_1h": 0.31, "win_rate": 52.9},
  ...
]
```

---

## 4. Pattern Fingerprint

Elke candle krijgt een fingerprint van 5 dimensies:

| Dimensie | Waarden |
|----------|---------|
| `rsi_zone` | oversold / neutral_low / neutral_high / overbought |
| `macd_direction` | bullish / bearish |
| `bb_position` | below_lower / lower_half / upper_half / above_upper |
| `ema_alignment` | bull / bear |
| `btc_trend` | bull / bear / neutral |

Voor elke unieke combinatie wordt uit de historische data berekend:
- Aantal voorgaande gevallen (precedenten)
- Gemiddelde PnL na 1h en 4h
- Win rate (% positief na 1h)
- Worst case (laagste PnL na 1h)

Minimaal 8 precedenten nodig voor een signaal. Anders: `HOLD`.

---

## 5. Integratie met apex_engine

`apex_engine` raadpleegt `indicator_engine` bij elke potentiële BUY via `_get_pattern_signal()`.

**Filter volgorde (BUY wordt alleen uitgevoerd als alle filters groen zijn):**

```
Signaal binnenkomt (BUY / BREAKOUT_BULL / MOMENTUM / PERFECT_DAY)
    │
    ├── RSI per-coin profiel      → RSI te hoog? BLOKKEER
    ├── BTC bearish filter        → BTC ema_bull=False en RSI<45? BLOKKEER
    ├── Signal blacklist          → (coin, signaal) structureel slecht? BLOKKEER
    └── Pattern engine            → AVOID? BLOKKEER | BUY? LOG BEVESTIGING
             │
             ▼
         BUY uitvoeren
```

**Log output voorbeeld:**
```
[pattern] XRPUSDT BUY geblokkeerd — pattern AVOID (win_rate=28%, pnl=-0.4%)
[pattern] SOLUSDT pattern bevestigt BUY (confidence=0.72, win_rate=63%, prec=18)
```

---

## 6. Automatische updates

De scheduler herhaalt elke 60 minuten een **incrementele update**:
- Haalt de laatste 50 candles op per coin per interval (Binance API)
- Slaat nieuwe candles op
- Herberekent indicatoren

De pattern database groeit zo automatisch mee naarmate meer marktdata beschikbaar komt.

---

## 7. Beschikbare coins (SAFE_COINS)

BTCUSDT, ETHUSDT, SOLUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, DOTUSDT,
UNIUSDT, LTCUSDT, DOGEUSDT, XRPUSDT, BNBUSDT, ADAUSDT, ATOMUSDT,
ARBUSDT, APTUSDT, SEIUSDT

---

## 8. Database tabellen

| Tabel | Inhoud |
|-------|--------|
| `ohlcv_data` | Ruwe candles: symbol, interval, ts, OHLCV |
| `indicators_data` | Berekende indicatoren per candle |
| `pattern_results` | Fingerprint + historische PnL per candle |

Alle tabellen zitten in de gedeelde PostgreSQL database (`apex`).

---

## 9. Handmatig gebruiken

```bash
# Health check
curl http://localhost:8099/health

# Historische import starten (12 maanden, alle coins)
curl -X POST http://localhost:8099/import \
  -H "Content-Type: application/json" \
  -d '{"months": 12}'

# Signaal opvragen voor BTCUSDT
curl http://localhost:8099/signal/BTCUSDT

# Data coverage bekijken
curl http://localhost:8099/coverage

# Patroon statistieken voor ETHUSDT
curl http://localhost:8099/patterns/ETHUSDT
```
