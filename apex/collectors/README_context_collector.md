# signal_context collector — Handoff voor Apex repo

## Wat doet dit?

Bij elke nieuwe rij in `signal_performance` wordt automatisch een indicator-snapshot
opgeslagen in de tabel `signal_context` (zelfde `apex.db`).

Doel: dataset opbouwen met *waarom* een signaal ontstond (RSI, MACD, ADX, etc.)
zodat later een lokale analyzer kan bepalen welke marktomstandigheden werken.

**Geen AI-calls. Geen externe API. Alleen `jojo_analytics:8097` intern.**

---

## Tabel: `signal_context`

| Kolom | Type | Beschrijving |
|---|---|---|
| `signal_perf_id` | INTEGER UNIQUE | FK naar `signal_performance.id` |
| `ts` | TEXT | Tijdstip signaal |
| `symbol` | TEXT | Coin (bijv. BTCUSDT) |
| `signal` | TEXT | BUY / MOMENTUM / BREAKOUT_BULL |
| `entry_price` | REAL | Prijs op moment van signaal |
| `tf_bias` | TEXT | bullish / bearish / neutral |
| `rsi_1h` | REAL | RSI op 1h timeframe |
| `rsi_oversold` | INTEGER | 1 als rsi < 35 |
| `rsi_overbought` | INTEGER | 1 als rsi > 65 |
| `macd_hist` | REAL | MACD histogram waarde |
| `macd_signal` | TEXT | bullish / bearish |
| `bb_width` | REAL | Bollinger Band breedte |
| `bb_position` | TEXT | low / mid / high |
| `adx` | REAL | ADX trendsterkte |
| `adx_strong` | INTEGER | 1 als adx > 25 |
| `stoch_rsi_k` | REAL | Stochastic RSI K |
| `stoch_rsi_d` | REAL | Stochastic RSI D |
| `ema21` | REAL | EMA 21 |
| `ema55` | REAL | EMA 55 |
| `ema200` | REAL | EMA 200 |
| `ema_bull` | INTEGER | 1 als ema21 > ema55 > ema200 |
| `advies` | TEXT | Advies van analytics engine |
| `raw_json` | TEXT | Volledige indicator response (JSON) |
| `collected_at` | TEXT | Tijdstip van verzameling |

---

## Script

**Actief pad (persistent):**
```
/root/.openclaw/workspace/tools/context_collector.py
```

**Backup pad (Docker volume, kan verdwijnen bij rebuild):**
```
/var/apex/context_collector.py
```

Gebruik altijd het workspace pad als canonical source.

---

## Opname in Apex repo

Aanbevolen locatie in de repo:
```
apex/
  collectors/
    context_collector.py    ← dit script
    README.md               ← deze file
```

Na opname in de repo: verwijder `/var/apex/context_collector.py` en
pas de cron-payload aan naar het nieuwe pad.

### Optioneel: als systemd service / Docker CMD

```bash
# Draai elke 10 minuten via crontab in de container:
*/10 * * * * python3 /app/collectors/context_collector.py >> /var/log/context_collector.log 2>&1
```

Of als aparte Docker service (aanbevolen voor productie):
```yaml
# docker-compose.yml toevoeging
context_collector:
  build: .
  command: >
    sh -c "while true; do python3 /app/collectors/context_collector.py; sleep 600; done"
  environment:
    - APEX_DB=/var/apex/apex.db
    - ANALYTICS_URL=http://jojo_analytics:8097
  volumes:
    - apex_data:/var/apex
```

---

## Environment variabelen

| Variabele | Default | Beschrijving |
|---|---|---|
| `APEX_DB` | `/var/apex/apex.db` | Pad naar SQLite database |
| `ANALYTICS_URL` | `http://jojo_analytics:8097` | jojo_analytics service |
| `OPENCLAW_TOOLS_LOG` | `/var/apex/openclaw_tools.log` | Log bestand |

---

## Status (7 maart 2026)

- ✅ Tabel `signal_context` aangemaakt in `apex.db`
- ✅ 150 historische signalen verrijkt (vanaf 4 mrt 2026)
- ✅ Cron actief: elke 10 min via OpenClaw gateway
- ⚠️ `/var/apex/context_collector.py` is tijdelijk — workspace versie is canonical
- ❌ `/workspace/tools/` is read-only (mount) — script staat daarom in `/root/.openclaw/workspace/tools/`

---

## Toekomstige stap: lokale analyzer

Zodra voldoende data verzameld is (aanbevolen: >500 verrijkte signalen per coin):

```sql
-- Voorbeeld analyse query: welke condities leveren positieve PnL op?
SELECT
    sc.signal,
    CASE WHEN sc.rsi_1h < 35 THEN 'oversold' ELSE 'normal' END as rsi_zone,
    sc.macd_signal,
    CASE WHEN sc.adx > 25 THEN 'trending' ELSE 'ranging' END as trend_strength,
    COUNT(*) as n,
    ROUND(AVG(sp.pnl_1h_pct), 3) as avg_pnl_1h,
    ROUND(AVG(sp.pnl_4h_pct), 3) as avg_pnl_4h
FROM signal_context sc
JOIN signal_performance sp ON sp.id = sc.signal_perf_id
WHERE sp.pnl_1h_pct IS NOT NULL
GROUP BY sc.signal, rsi_zone, sc.macd_signal, trend_strength
ORDER BY avg_pnl_1h DESC;
```

Dit geeft direct inzicht in welke combinaties van indicatoren werken —
zonder AI-calls.
