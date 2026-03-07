# Data & Analyse Architecture — OpenClaw Apex Trading Platform

**Versie:** 1.0 (2026-03-07)
**Doel:** Technisch overzicht van alle data- en analyselagen voor architectuurreview en AI-analyse.

---

## 1. Database Overzicht

Het platform gebruikt twee databases parallel:

| Database | Locatie | Gebruikt door |
|----------|---------|---------------|
| **PostgreSQL 16** | `postgres` container, poort 5432, database `apex` | indicator_engine, apex_engine, control_api, kimi_pattern_agent, jojo_analytics |
| **SQLite** (`apex.db`) | Docker volume `/var/apex/apex.db` | apex_engine (live trading data, signal_context, verdict_log) |

---

### 1.1 ohlcv_data (PostgreSQL)

| Eigenschap | Waarde |
|---|---|
| **Records** | 1.390.981 |
| **Coins** | 40 |
| **Timeframes** | 1h, 4h |
| **Periode** | 2017-08-17 → heden (live bijgewerkt) |
| **Bron** | Binance API — `indicator_engine` import |

**Kolommen:** `symbol, interval, ts, open, high, low, close, volume`

**Doel:** Ruwe OHLCV prijsdata. Basis voor alle indicatorberekeningen.

**Vulling:** `POST /import` op indicator_engine haalt historische candles op van Binance. Daarna incrementele update elke 60 minuten via APScheduler.

---

### 1.2 indicators_data (PostgreSQL)

| Eigenschap | Waarde |
|---|---|
| **Records** | 1.350.937 |
| **Coins** | 40 |
| **Timeframes** | 1h (988.476 rijen), 4h (362.461 rijen) |
| **Periode** | 2017-08-26 → heden |
| **Bron** | Berekend door indicator_engine op basis van ohlcv_data |

**Kolommen:**
```
id, symbol, interval, ts,
rsi, rsi_zone,
macd_hist,
bb_width, bb_position,
ema21, ema55, ema200, ema_bull,
adx, stoch_rsi_k, stoch_rsi_d,
atr, volume_ratio
```

**Indicatoren:**
| Indicator | Periode/Instelling |
|---|---|
| RSI | 14 perioden |
| RSI zone | oversold (<35) / mid-low / mid-high / overbought (>65) |
| MACD histogram | 12/26/9 EMA |
| Bollinger Bands | 20 perioden, 2 std — breedte + positie (low/mid/high) |
| EMA21 / EMA55 / EMA200 | Exponential Moving Average |
| ema_bull | boolean: ema21 > ema55 > ema200 |
| ADX | 14 perioden — trendsterkte |
| StochRSI K/D | 14/3/3 |
| ATR | 14 perioden — volatility |
| volume_ratio | volume / gemiddeld volume (20 perioden) |

**Doel:** Pre-berekende indicator-snapshots voor elke candle per coin. Maakt snelle lookups mogelijk zonder real-time herberekening.

**Vulling:** Na OHLCV import berekent indicator_engine via TA-Lib alle indicatoren en slaat ze op.

---

### 1.3 historical_backtest (PostgreSQL)

| Eigenschap | Waarde |
|---|---|
| **Records** | 47.306 |
| **Coins** | 25 |
| **Periode** | 2018-05-13 → 2026-03-06 |
| **Bron** | apex_engine backtesting op basis van eigen signaallogica |

**Kolommen:**
```
id, run_ts, symbol, interval, months,
candle_ts, signal, active_signals,
entry_price,
price_1h, price_4h, price_24h,
pnl_1h_pct, pnl_4h_pct, pnl_24h_pct
```

**Signaalverdeling:** BUY, BREAKOUT_BULL, MOMENTUM

**Doel:** Historische backtestresultaten — per signaal: entry prijs + PnL op 1h/4h/24h na entry. Bevat **geen** indicatorwaarden op moment van signaal (daarvoor: historical_context).

**Coins met meeste records:**
| Coin | Records | Periode |
|---|---|---|
| XRPUSDT | 32.162 | 2018-05-13 → 2026-03-06 |
| SOLUSDT | 6.563 | 2025-03-19 → 2026-03-05 |
| BTCUSDT | 2.454 | 2025-09-14 → 2026-03-06 |
| AAVEUSDT | 922 | 2025-12-15 → 2026-03-05 |

---

### 1.4 historical_context (PostgreSQL) ← NIEUW

| Eigenschap | Waarde |
|---|---|
| **Records** | 31.246 (66.1% van historical_backtest) |
| **Coins** | 21 |
| **Periode** | 2022-01-31 → 2026-03-06 |
| **Bron** | JOIN van historical_backtest × indicators_data |

**Kolommen:**
```
id, backtest_id (FK → historical_backtest.id),
symbol, candle_ts, signal,
pnl_1h_pct, pnl_4h_pct, pnl_24h_pct,
rsi, rsi_zone,
macd_hist,
bb_width, bb_position,
ema21, ema55, ema200, ema_bull,
adx, stoch_rsi_k, stoch_rsi_d,
volume_ratio, atr,
enriched_at
```

**Doel:** De **kernanalyse dataset**. Koppelt historische signaaluitkomsten (PnL) aan de indicatorwaarden die op dat moment actief waren. Maakt het mogelijk te beantwoorden: "onder welke marktomstandigheden werkt signaaltype X het best?"

**Vulling:** `POST /historical-enrich` op indicator_engine voert de JOIN uit. Automatisch bij startup (2 min na start) en na elke nieuwe coin import.

**Ontbrekende 34% (16.060 records):**
- XRPUSDT pre-2022 records (15.137) — indicators_data begint pas bij 2022 voor XRP in backtest-periode
- FILUSDT (289), USDCUSDT (264 — stablecoin), SUIUSDT (189), WIFUSDT (181) — geen match in indicators_data

**Coverage per coin:**
```
XRPUSDT:    17.025 / 32.162 (53%)   SOLUSDT:  6.563 / 6.563  (100%)
BTCUSDT:     2.454 / 2.454  (100%)  AAVEUSDT:   922 / 922    (100%)
UNIUSDT:       334 / 334    (100%)  TRXUSDT:    321 / 321    (100%)
HBARUSDT:      288 / 288    (100%)  DOTUSDT:    279 / 279    (100%)
RENDERUSDT:    277 / 277    (100%)  + 12 meer coins 100%
```

---

### 1.5 signal_performance (PostgreSQL)

| Eigenschap | Waarde |
|---|---|
| **Records** | 552 |
| **Coins** | 25 |
| **Periode** | 2026-03-04 → heden (live) |
| **Bron** | apex_engine — elke signaalopslag tijdens live trading loop |

**Kolommen:**
```
id, ts, symbol, signal, active_signals, entry_price,
price_15m, price_1h, price_4h,
pnl_15m_pct, pnl_1h_pct, pnl_4h_pct, pnl_24h_pct
```

**Doel:** Live signaalresultaten. Equivalent van historical_backtest maar voor lopende activiteit.

---

### 1.6 signal_context (SQLite — apex.db)

| Eigenschap | Waarde |
|---|---|
| **Records** | 467 |
| **Coins** | 24 |
| **Periode** | 2026-03-04 → heden |
| **Bron** | context_collector.py cron — haalt indicators op via jojo_analytics:8097 |

**Kolommen:**
```
id, signal_perf_id (FK → signal_performance),
ts, symbol, signal, entry_price, tf_bias,
rsi_1h, rsi_oversold, rsi_overbought,
macd_hist, macd_signal,
bb_width, bb_position,
adx, adx_strong,
stoch_rsi_k, stoch_rsi_d,
ema21, ema55, ema200, ema_bull,
advies, raw_json, collected_at
```

**Doel:** Live equivalent van historical_context — indicator-snapshot bij elk live signaal.

**Vulling:** `context_collector.py` draait als OpenClaw cron elke 10 minuten. Detecteert nieuwe signal_performance records, haalt indicators op via `POST jojo_analytics:8097/indicators`, slaat op.

---

### 1.7 verdict_log (SQLite — apex.db)

| Eigenschap | Waarde |
|---|---|
| **Records** | 167 |
| **Bron** | context_collector.py + setup_judge.py |

**Kolommen:**
```
id, signal_perf_id, ts, symbol, signal,
rsi_1h, macd_signal, adx, rsi_zone, adx_strong,
verdict (SKIP/TWIJFEL/TOESTAAN/ONBEKEND),
confidence (laag/midden/hoog), n,
avg_1h, avg_4h, win_pct_1h,
conflict, matched_level, reden, logged_at
```

**Doel:** Logt het verdict van setup_judge per signaal. Wordt gebruikt voor evaluatie: presteren SKIP-verdicts ook echt slechter dan TOESTAAN-verdicts?

**Verdeling (167 records):** SKIP: 5 | TOESTAAN: 11 | TWIJFEL: ~151

---

### 1.8 Overige tabellen (SQLite)

| Tabel | Records | Doel |
|---|---|---|
| `demo_account` | 162 | Virtuele trades in demo mode |
| `orders` | 1.395 | Alle uitgaande demo orders naar BloFin |
| `market_context` | 277 | BTC marktcontext snapshots (RSI, tf_bias) per evaluatierun |
| `price_snapshots` | 1.051 | Prijs + indicator momentopnames per coin |
| `crash_score_log` | 1.051 | Pre-crash score per coin per run |

---

## 2. Data Pipeline

```
Binance API (publiek)
        │
        ▼
indicator_engine: POST /import
        │
        ▼
ohlcv_data (PostgreSQL)
  40 coins × 2 timeframes × 2017 → nu
  1.390.981 candles
        │
        ▼
TA-Lib indicator berekening
(RSI, MACD, EMA21/55/200, ADX, BB, StochRSI, ATR, volume_ratio)
        │
        ▼
indicators_data (PostgreSQL)
  1.350.937 rijen × 18 kolommen
        │
        ├──────────────────────────────────────┐
        ▼                                      ▼
historical_backtest                    live trading loop
(47.306 signalen, 2018-2026)          (apex_engine, elke 10s)
        │                                      │
        ▼ POST /historical-enrich              ▼
historical_context (PostgreSQL)        signal_performance (PostgreSQL)
  31.246 verrijkte signalen                552 live signalen
  = backtest + indicatorwaarden                │
        │                              context_collector (cron 10min)
        │                                      │
        │                                      ▼
        │                              signal_context (SQLite)
        │                                467 records + verdicts
        │                                      │
        └──────────────────┬───────────────────┘
                           ▼
                    setup_judge.py
              (SKIP / TWIJFEL / TOESTAAN)
                    advieslaag
                           │
                           ▼ (toekomstig)
                    apex_engine filter
                    trading beslissing
```

---

## 3. Indicator Engine

**Container:** `indicator_engine`, poort `8099`
**Stack:** Python 3.12, FastAPI, TA-Lib, APScheduler, psycopg2

### Indicatoren

| Indicator | Instelling | Timeframes | Beschrijving |
|---|---|---|---|
| RSI | 14 perioden | 1h, 4h | Relative Strength Index |
| RSI zone | thresholds 35/65 | 1h, 4h | oversold / mid-low / mid-high / overbought |
| MACD histogram | 12/26/9 | 1h, 4h | MACD - Signal line |
| Bollinger Band breedte | 20/2σ | 1h, 4h | (upper-lower)/mid × 100 |
| Bollinger Band positie | 20/2σ | 1h, 4h | low / mid / high |
| EMA21 | 21 perioden | 1h, 4h | Exponential MA snel |
| EMA55 | 55 perioden | 1h, 4h | Exponential MA middellang |
| EMA200 | 200 perioden | 1h, 4h | Exponential MA lang |
| ema_bull | — | 1h, 4h | boolean: ema21 > ema55 > ema200 |
| ADX | 14 perioden | 1h, 4h | Average Directional Index (trendsterkte) |
| StochRSI K | 14/3/3 | 1h, 4h | Stochastic RSI K-lijn |
| StochRSI D | 14/3/3 | 1h, 4h | Stochastic RSI D-lijn (signal) |
| ATR | 14 perioden | 1h, 4h | Average True Range (volatility) |
| volume_ratio | 20 perioden | 1h, 4h | volume / gemiddeld volume |

### Update frequentie

| Job | Frequentie | Beschrijving |
|---|---|---|
| `incremental_update` | Elke 60 min | Nieuwe candles ophalen + indicators herberekenen |
| `coin_watcher` | Elke 30 min | Nieuwe coins detecteren en auto-importeren |
| `initial_enrich` | 2 min na startup | historical_context opbouwen/bijwerken |

### Endpoints

| Endpoint | Methode | Beschrijving |
|---|---|---|
| `/health` | GET | Status + scheduled jobs |
| `/import` | POST | Historische data importeren (`symbols`, `months`) |
| `/indicators/{symbol}` | GET | Huidige indicator-snapshot voor coin |
| `/signal/{symbol}` | GET | Historisch signaal + win rate |
| `/patterns/{symbol}` | GET | Patroon-precedenten |
| `/coverage` | GET | Data coverage per coin |
| `/sniper/set` | POST | Sniper instellen (dip/short/breakout/niveau) |
| `/sniper/list` | GET | Actieve snipers |
| `/sniper/{id}` | DELETE | Sniper annuleren |
| `/reverse-backtest` | POST | Pre-crash fingerprint analyse |
| `/historical-enrich` | POST | Historical context enrichment starten |
| `/historical-enrich/status` | GET | Coverage + voortgang enrichment |
| `/coin-watcher/status` | GET | Actieve vs gedekte coins |

---

## 4. Historical Dataset

| Eigenschap | OHLCV Data | Indicator Data |
|---|---|---|
| **Tabel** | `ohlcv_data` | `indicators_data` |
| **Records** | 1.390.981 | 1.350.937 |
| **Coins** | 40 | 40 |
| **Timeframes** | 1h + 4h | 1h + 4h |
| **Periode** | 2017-08-17 → nu | 2017-08-26 → nu |
| **Gemiddeld per coin** | ~34.774 OHLCV rijen | ~33.773 indicator rijen |

**40 coins:**
BTC, ETH, SOL, AAVE, AVAX, LINK, DOT, UNI, LTC, DOGE, XRP, BNB, ADA, ATOM, ARB, APT, SEI, SUI, TRX, NEAR, BCH, ICP, HBAR, PEPE, WIF, WLD, ENA, TAO, ZEC, OP, XLM, SHIB, FET, BONK, FLOKI, RENDER, INJ, TIA, ALGO, VET

---

## 5. Historical Context Dataset

| Eigenschap | Waarde |
|---|---|
| **Tabel** | `historical_context` (PostgreSQL) |
| **Records** | 31.246 |
| **Coins** | 21 |
| **Periode** | 2022-01-31 → 2026-03-06 |
| **Coverage** | 66.1% van historical_backtest |

### Wat het bevat

Voor elke historische backtest-signaal (BUY/BREAKOUT_BULL/MOMENTUM):
- Het signaalmoment + entry prijs
- PnL op 1h, 4h, 24h na entry
- Alle indicatorwaarden op dat exacte moment (RSI, MACD, EMA21/55/200, ADX, BB, StochRSI, volume_ratio)

### Enrichment proces

```
historical_backtest (47.306 records)
        │ JOIN op (symbol, candle_ts::timestamptz, interval='1h')
indicators_data (1.350.937 records)
        │
        ▼
historical_context (31.246 records)
  = 66.1% match
```

**Ontbrekende 33.9%:**
- Pre-2022 XRPUSDT records (backtest gaat terug tot 2018, indicators_data dekking voor XRP begint later)
- FILUSDT / SUIUSDT / WIFUSDT — nog geen of onvoldoende indicator coverage

### Gebruik

Dit is de primaire dataset voor setup_judge en toekomstige strategie-analyse. Bevat voldoende n (31k+ records) voor statistische uitspraken over welke marktomstandigheden werken.

---

## 6. Coin Auto-Discovery

Wanneer de trading engine een nieuwe coin gaat volgen, wordt de data-infrastructuur automatisch bijgewerkt:

```
apex_engine: nieuwe coin in SAFE_COINS
        │
        ▼ signalen verschijnen in signal_performance
indicator_engine: _check_new_coins() (elke 30 min)
        │ detecteert coin in signal_performance maar niet in indicators_data
        ▼
_import_symbol(coin, '1h', months=48)
        │ fetch historische OHLCV van Binance
        ▼
ohlcv_data + indicators_data gevuld
        │
        ▼
_run_historical_enrich()
        │ JOIN met historical_backtest voor nieuwe coin
        ▼
historical_context bijgewerkt
        │
        ▼
coin_watcher /status toont: missing_coverage = []
```

**Handmatig (via Jojo1 of CLI):**
```bash
python3 coin_watcher.py --status          # overzicht
python3 coin_watcher.py --force NEWCOIN   # forceer import
python3 coin_watcher.py --enrich          # trigger enrichment
```

---

## 7. API Endpoints — Data Laag

### indicator_engine (poort 8099)

| Endpoint | Methode | Input | Output |
|---|---|---|---|
| `/historical-enrich` | POST | — | `{status, message}` — start enrichment in achtergrond |
| `/historical-enrich/status` | GET | — | `{enriched, total_backtest, coverage_pct, coins, date_range, running}` |
| `/coin-watcher/status` | GET | — | `{active_coins, covered_coins, missing_coverage, missing_count}` |
| `/import` | POST | `{symbols, months}` | `{status, started}` |
| `/indicators/{symbol}` | GET | `?interval=1h` | Volledige indicator-snapshot |
| `/coverage` | GET | — | Coverage per coin |

### jojo_analytics (poort 8097)

| Endpoint | Methode | Input | Output |
|---|---|---|---|
| `/query` | POST | `{sql: "SELECT ..."}` | `{rows, columns, count}` — max 200 rijen |
| `/indicators` | POST | `{symbol, interval, limit}` | Live indicator-snapshot via Binance |
| `/health` | GET | — | `{status}` |

---

## 8. Setup Judge Integratie

### Huidige werking

`setup_judge.py` is een Python tool die draait in de OpenClaw gateway workspace.

**Databron:** SQLite (`/var/apex/apex.db`) — gebruikt `signal_context` + `signal_performance`

**Lookup-logica (3 niveaus, meest specifiek wint):**
```
1. Generiek:      signal + rsi_zone + macd_signal + adx_strong
2. Coin + RSI:    symbol + signal + rsi_zone
3. Coin algemeen: symbol + signal (alle condities)
```

**Output:**
```json
{
  "verdict": "SKIP | TWIJFEL | TOESTAAN | ONBEKEND",
  "confidence": "laag | midden | hoog",
  "n": 47,
  "avg_pnl_1h": -0.43,
  "win_pct_1h": 0.21,
  "reden": "BUY + oversold RSI + bullish MACD: 0% win rate (n=12)"
}
```

### Huidige dataset: signal_context (live)
- **467 records**, 24 coins, 3 dagen
- Voldoende voor eerste indicaties, te weinig voor harde regels

### Volgende stap: historical_context (aanbevolen)
- **31.246 records**, 21 coins, 4 jaar
- 66× meer data → veel betrouwbaardere verdicts
- Integratie vereist: setup_judge aanpassen om `jojo_analytics /query` te gebruiken voor historical_context aggregaten (PostgreSQL)

### Twee datasets naast elkaar

| Dataset | Records | Periode | Sterkte | Zwakte |
|---|---|---|---|---|
| `signal_context` (live) | 467 | 3 dagen | Actueel marktregime | Te weinig n |
| `historical_context` | 31.246 | 4 jaar | Grote n, statistisch sterk | Historisch — huidig regime kan afwijken |

**Aanbevolen combinatie:** historical_context als primaire basis, signal_context als recente correctie-laag.

---

## 9. Huidige Limieten

| Beperking | Impact | Oplossing |
|---|---|---|
| setup_judge gebruikt alleen signal_context (467 records) | Verdicts gebaseerd op kleine n, onbetrouwbaar | Integreer historical_context |
| historical_context 33.9% ontbrekend | XRPUSDT pre-2022, FILUSDT/SUIUSDT/WIFUSDT | Extend indicator import voor deze coins |
| signal_context / verdict_log in SQLite, historical_context in PostgreSQL | Twee query-paden voor setup_judge | Migreer signal_context naar PostgreSQL, of gebruik /query endpoint |
| setup_judge is advieslaag — blokkeert niets | Signaalfiltering heeft geen effect op trades | Integreer met apex_engine na voldoende validatie |
| historical_backtest mist indicator-context voor pre-2022 XRP | Grootste coin (32k records) maar slechts 53% verrijkt | Import XRP OHLCV data terug tot 2018 |
| Geen regime-labeling in historical_context | Kan niet filteren op bull/bear/sideways regime | Voeg regime kolom toe via BTC EMA200 op candle_ts |
| jojo_analytics /query limiet: 200 rijen | Ruwe data queries beperkt | Aggregate queries werken wel; voor bulk: directe DB |

---

## 10. Volgende Technische Stappen (Dev Perspectief)

### P0 — Directe waarde, lage complexiteit

**1. setup_judge integreren met historical_context**
- Huidige setup_judge gebruikt 467 records (3 dagen)
- Aanpassing: gebruik `jojo_analytics /query` voor aggregaten op historical_context
- Resultaat: 31.246 records als basis → betrouwbare SKIP/TOESTAAN regels

**2. Regime-label toevoegen aan historical_context**
- Per record: was BTC boven of onder EMA200 op dat moment?
- Kolom: `btc_regime` (bull/bear)
- Waarde: kan direct berekend worden via indicators_data JOIN op BTCUSDT candle_ts

**3. XRPUSDT historische gap opvullen**
- 15.137 records ontbreken context (pre-2022)
- Fix: extended import van XRPUSDT OHLCV terug tot 2018

### P1 — Daarna

**4. signal_context migreren naar PostgreSQL**
- Elimineert de SQLite / PostgreSQL split
- Maakt directe JOINs mogelijk met historical_context

**5. apex_engine integratie setup_judge**
- Bij elk nieuw signaal: setup_judge raadplegen
- Als SKIP + confidence hoog: signaal niet uitvoeren
- Als TWIJFEL: doorgaan, maar lagere positiegrootte

**6. Regime engine (standalone)**
- Extraheer BTC EMA200 / EMA21/55 logica uit apex_engine
- Los component dat huidig marktregime bepaalt
- Output: `{regime: "bull_trend", confidence: 0.78}`

### P2 — Strategie Portfolio Manager

**7. Strategy Portfolio Manager**
- meanrev_rsi_dip_v1, trend_breakout_v1, crash_defense_v1, post_crash_rebound_v1
- Gewichten per strategie op basis van regime + performance
- Kimi2 nachtanalyse als advieslaag

**8. Event Intelligence Layer**
- Flash crash detectie op basis van historical fingerprints
- Vergelijkbare historische events zoeken bij nieuwe alerts

---

---

## 11. AI-vrije Kernarchitectuur

> **Dit zijn geharde principes, geen aanbevelingen.**
> Ze gelden voor alle toekomstige wijzigingen aan het platform.

De datafundering is sterk genoeg om de trading intelligence **primair statistisch en regelgedreven** te maken. Externe AI hoeft niet in de realtime beslisloop en kan beperkt blijven tot rapportage, research en samenvatting.

### Kernprincipes (niet onderhandelbaar)

**1. Geen AI in de realtime beslisloop**

De volgende componenten mogen nooit afhankelijk worden van een LLM-call (Claude, Kimi, GPT, of andere):
- `apex_engine` — signaalfiltering, stoploss, positionering
- `setup_judge` — historische verdict op setup
- `signal_blacklist` — coin/signal blacklist op PnL
- `coin_watcher` — nieuwe coin detectie
- `context_collector` — indicator snapshot

Als een van deze componenten faalt doordat een AI-service niet beschikbaar is, is dat een architectuurfout.

**2. Fail-safe als AI uitvalt**

Als Jojo1 (openclaw_gateway) of Kimi (tg_discuss_bot) niet beschikbaar is:
- `apex_engine` blijft gewoon draaien — geen handshake vereist
- `setup_judge` blijft werkzaam — alleen PostgreSQL vereist
- Filters en blacklist blijven actief — volledig regelgedreven
- Telegram rapportage stopt — dit is acceptabel (informatie, geen executie)

Het platform is zo ontworpen dat **uitval van alle AI-services geen impact heeft op orderuitvoering**.

**3. Geen directe ordercontrole door AI**

Claude (Jojo1) en Kimi hebben **geen directe toegang** tot order-executie endpoints:
- Zij mogen `control_api` bevelen geven via parameters (config_overrides)
- Zij mogen signalen analyseren en rapporteren
- Zij mogen **nooit** direct `POST /trade`, `POST /order` of gelijkwaardige endpoints aanroepen
- Alle orders lopen uitsluitend via `apex_engine` → `blofin_client`

De scheiding: AI = advieslaag / statistiek = beslislaag / apex_engine = executielaag.

**4. Datastromen zijn uni-directioneel**

```
REALTIME BESLISLOOP (geen AI)          AI LAAG (asynchroon, read-only)
─────────────────────────────          ────────────────────────────────
indicators_data                        Jojo1 (OpenClaw)
      ↓                                  → marktanalyse (leest data)
historical_context                       → samenvatting voor Frans
      ↓                                  → config_overrides voorstellen
setup_judge (pure SQL)                 Kimi2 (nachtanalyse)
      ↓                                  → regime advies (leest data)
apex_engine filter                       → strategie bias rapporteren
      ↓
trading beslissing                     ← AI heeft hier geen schrijftoegang
      ↓
blofin_client → exchange
```

**5. Statistiek gaat boven AI-oordeel**

Als `setup_judge` (historische data, n≥10) SKIP zegt voor een setup, dan geldt dat SKIP — ongeacht wat Jojo1 of Kimi rapporteert. AI-signalen zijn informatief, niet bindend.

### Wat de statistiek beslist

| Beslissing | Hoe | AI nodig? |
|---|---|---|
| Is deze setup historisch winstgevend? | historical_context aggregaat (31k records) | Nee |
| Welke coins presteren het slechtst? | signal_analyzer per coin | Nee |
| Is de markt trending of ranging? | ADX drempel + EMA alignment | Nee |
| Is BTC in bull of bear regime? | btc_regime in historical_context (EMA200) | Nee |
| Welke signalen zijn blacklist-kandidaat? | PnL < drempel + min n | Nee |
| Wanneer is een coin SKIP? | setup_judge — 3 niveaus, 31k records | Nee |

### Wat AI wél doet

| Taak | AI | Frequentie |
|---|---|---|
| Marktrapport naar Frans | tg_coordinator_bot (Kimi) | Elke 30 min |
| Nachtanalyse regime + strategie | kimi_pattern_agent | 03:00 dagelijks |
| Marktuitleg op verzoek | tg_discuss_bot (Kimi) | Op aanvraag |
| Jojo1 operator beslissingen | openclaw_gateway (Claude) | Op events |
| Research bij bijzondere events | Jojo1 Research Agent | Op aanvraag |
| Config voorstel (drempels aanpassen) | Jojo1 → control_api proposals | Op aanvraag |

### Gevolg voor systeemkosten

Alle realtime filtering draait op eigen hardware, zonder externe API-calls:
- `setup_judge` → pure SQL op PostgreSQL (intern)
- `signal_analyzer` → pure SQL aggregaties (intern)
- `context_collector` → REST call naar jojo_analytics (intern)
- `coin_watcher` → REST call naar indicator_engine (intern)

AI-kosten (Anthropic credits) worden alleen gemaakt bij:
1. Jojo1 reageert op Telegram bericht van Frans
2. Jojo1 voert een actieve analyse uit (Research/Risk Agent)
3. Kimi2 nachtrapport (Moonshot API, goedkoper)

**Conclusie:** het platform draait volledig zonder AI-credits. AI verbetert de kwaliteit van beslissingen en communicatie, maar de kernbescherming (filters, skip-regels, blacklist, btc_regime) is volledig statistisch en regelgedreven en faalt nooit door AI-uitval.

---

*Gegenereerd: 2026-03-07 | Basis: live database queries op PostgreSQL + SQLite apex.db*
