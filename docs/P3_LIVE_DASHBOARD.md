# P3 — Live Dashboard, Chart Markers & Signal Detection

Versie: 2026-03-07 | Platform: OpenClaw Apex v2

---

## Overzicht

P3 voegt drie grote lagen toe bovenop het P1/P2 fundament:

1. **Live Signalen pagina** — actuele RSI/MACD/ADX per coin, actief signaaltype, P1 verdict
2. **Chart markers** — 3 soorten markers op één grafiek: Setup Intel momenten + testbot entries + testbot exits
3. **Setup Intelligence verbeteringen** — "Laatste signaal" kolom, nieuwe API endpoints

---

## 1. Live Signalen (`live_signals.html`)

### Doel
Een scherm dat toont: *welke coins geven NU een signaal, wat zijn de actuele indicator waarden, en wat is het historische advies?*

Dit is fundamenteel anders dan Setup Intelligence:
- **Setup Intelligence** = historische kwaliteit van een signaaltype (aggregaat over 4 jaar)
- **Live Signalen** = actuele marktomstandigheden + actief signaal + P1 verdict voor die combo

### Signaaldetectie (`_detect_signal()` in server.py)

Gebruikt de meest recente rij uit `indicators_data` (interval=1h) per coin:

| Signal | Condities |
|--------|-----------|
| `BREAKOUT_BULL` | `bb_position = 'above_upper'` AND `rsi > 50` AND `volume_ratio > 1.5` |
| `MOMENTUM` | `ema_bull = True` AND `50 < rsi < 65` AND `macd_hist > 0` AND `adx > 25` |
| `BUY` | `rsi < 32` AND `macd_hist > 0`, OF StochRSI oversold (`sk < 20` AND `sk > sd` AND `rsi < 45`) |

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

Gesorteerd op: actief signaal eerst → verdict kwaliteit → laagste RSI.

### Frontend

- Auto-refresh elke 60 seconden
- Filter: Alles / Met signaal / Alleen STERK+TOESTAAN
- Klik op rij → detail panel met plain-language interpretatie
- Live prijzen via Binance public REST API (browser-side fetch)
- Status bar: BTC regime, aantal actieve signalen, aantal STERK actief

---

## 2. Chart Markers

### Drie markertypen op één grafiek

#### 2a. Setup Intel markers (historisch)

**Endpoint:** `GET /setup/chart-markers/{symbol}?days=180`

Logica:
1. Bereken aggregate verdict per signaaltype voor dit symbool (zelfde als `/setup/scan`)
2. Haal alle historische candles op uit `historical_context` voor de laatste `days` dagen
3. Koppel elk candle aan het aggregate verdict van zijn signaaltype
4. Geef alleen STERK / TOESTAAN / TOESTAAN_ZWAK terug (SKIP = ruis, weggelaten)

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

Haalt alle `testbot_trades` op voor het symbool, geeft entries terug:
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

Zelfde endpoint, `exits` array:
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

### Visueel onderscheid

| Marker | Kleur | Vorm | Tekst |
|--------|-------|------|-------|
| Setup STERK | #3fb950 groen | arrowUp belowBar | `STERK(BB) +0.79%` |
| Setup TOESTAAN | #58a6ff blauw | arrowUp belowBar | `TOES(MOM) +0.42%` |
| Setup TOESTAAN_ZWAK | #d29922 geel | arrowUp belowBar | `ZWAK(BUY) -0.01%` |
| Bot entry | #3fb950 groen | arrowUp belowBar | `BOT s78` |
| Bot exit TP | #58a6ff blauw | circle aboveBar | `TP +4.35$` |
| Bot exit SL | #f85149 rood | square aboveBar | `SL -2.10$` |
| Bot exit TIMEOUT | #d29922 geel | square aboveBar | `TMT +0.52$` |

### Timestamp snapping

LW Charts vereist dat `marker.time` exact overeenkomt met een candle-open tijd. De `snapToCandle()` functie floort elke timestamp naar het candle-interval:

```js
function snapToCandle(unixSec) {
  const secs = {"1h": 3600, "4h": 14400, "15m": 900, "5m": 300}[_tf] || 3600;
  return Math.floor(unixSec / secs) * secs;
}
```

### Klik-handler

Prioriteit bij klik: bot exit → bot entry → setup marker:
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

## 3. Setup Intelligence verbeteringen

### "Laatste signaal" kolom

Query uitbreiding in `/setup/scan`:
```sql
MAX(candle_ts) as last_signal_ts
```

`_sj_process_row()` berekent `last_signal_hours_ago` en geeft dit terug in de response.

Frontend `lastSignalFmt()`:
- `≤ 6 uur` → **Nu actief** (groen vet)
- `≤ 24 uur` → `Xh geleden` (groen)
- `≤ 72 uur` → `Xd geleden` (geel)
- `> 72 uur` → `Xd geleden` (grijs)

### Marker label met signaalafkorting

Markers op de grafiek tonen nu de signaalafkorting zodat `STERK(BB)` vs `ZWAK(BUY)` duidelijk is:
```js
const sigAbbr = {"BREAKOUT_BULL":"BB","MOMENTUM":"MOM","BUY":"BUY"}[v.signal];
const label = `${verdictLabel}(${sigAbbr})${pnlStr}`;
```

---

## Gewijzigde bestanden

| Bestand | Wijziging |
|---------|-----------|
| `control_api/app/server.py` | `_detect_signal()`, `GET /live/signals`, `GET /setup/chart-markers/{sym}`, `GET /testbot/markers/{sym}`, last_signal_ts in scan |
| `dashboard/live_signals.html` | Nieuw — complete live signalen pagina |
| `dashboard/chart.html` | 3 markertypen, snapToCandle, click handler, Setup Intel toggle |
| `dashboard/setup_intelligence.html` | "Laatste signaal" kolom, `lastSignalFmt()` helper |
| `dashboard/index.html` | ⚡ Live knop toegevoegd aan navigatie |
