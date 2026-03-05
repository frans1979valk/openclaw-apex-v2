"""Kimi Pattern Agent — nachtelijke patroonanalyse op historische data."""
import os, json, sqlite3, logging, time
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests as req
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("kimi_pattern_agent")

app = FastAPI(title="Kimi Pattern Agent")

# ── Config ────────────────────────────────────────────────────────────────────
KIMI_API_KEY  = os.getenv("KIMI_API_KEY", "")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
KIMI_MODEL    = os.getenv("KIMI_MODEL", "moonshot-v1-32k")
BINANCE_BASE  = os.getenv("BINANCE_BASE", "https://api.binance.com")
DB_PATH       = "/var/apex/apex.db"
REPORT_DIR    = "/var/apex"
TG_BOT_TOKEN  = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID    = os.getenv("TG_CHAT_ID", "")
TRACKED_COINS = os.getenv("TRACKED_COINS", "BTCUSDT,ETHUSDT,SOLUSDT,AVAXUSDT,AAVEUSDT").split(",")
# Nachtelijke analyse uur (UTC)
ANALYSIS_HOUR = int(os.getenv("ANALYSIS_HOUR", "3"))


# ── Binance OHLCV ────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
    r = req.get(f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=15)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_buy_vol", "taker_buy_quote", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]


# ── Indicator berekening (pure numpy) ────────────────────────────────────────

def calc_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    result = np.full(len(close), np.nan)
    if len(close) < period + 1:
        return result
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            result[i + 1] = 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def calc_ema(values: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(values), np.nan)
    if len(values) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(values[:period])
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


# ── OHLCV opslaan in DB ──────────────────────────────────────────────────────

def ensure_ohlcv_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS ohlcv_history(
        symbol TEXT NOT NULL,
        interval TEXT NOT NULL,
        ts TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        UNIQUE(symbol, interval, ts)
    )""")
    conn.commit()
    conn.close()


def store_ohlcv(symbol: str, interval: str, df: pd.DataFrame):
    conn = sqlite3.connect(DB_PATH)
    for _, row in df.iterrows():
        try:
            conn.execute(
                """INSERT OR IGNORE INTO ohlcv_history(symbol, interval, ts, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, interval, row["ts"].isoformat(), row["open"], row["high"], row["low"], row["close"], row["volume"])
            )
        except Exception:
            pass
    conn.commit()
    conn.close()


def collect_all_ohlcv():
    """Haal OHLCV data op voor alle tracked coins en sla op in DB."""
    ensure_ohlcv_table()
    for symbol in TRACKED_COINS:
        symbol = symbol.strip()
        if not symbol:
            continue
        try:
            for interval in ["1h", "4h"]:
                df = fetch_ohlcv(symbol, interval, limit=500)
                store_ohlcv(symbol, interval, df)
                log.info(f"OHLCV opgeslagen: {symbol} {interval} ({len(df)} candles)")
                time.sleep(0.5)  # Rate limit
        except Exception as e:
            log.error(f"OHLCV fout voor {symbol}: {e}")


# ── DB analyse helper ────────────────────────────────────────────────────────

def get_signal_stats() -> dict:
    """Haal signaal performance statistieken op uit de DB."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        # Signaal performance per coin
        cur = conn.execute("""
            SELECT symbol, signal, COUNT(*) as n,
                   ROUND(AVG(pnl_1h_pct), 3) as avg_pnl_1h,
                   ROUND(AVG(pnl_4h_pct), 3) as avg_pnl_4h
            FROM signal_performance
            WHERE ts > datetime('now', '-7 days')
            GROUP BY symbol, signal
            ORDER BY avg_pnl_1h DESC
        """)
        signal_perf = [dict(r) for r in cur.fetchall()]

        # Demo account trades
        cur = conn.execute("""
            SELECT symbol, action, COUNT(*) as n,
                   ROUND(AVG(virtual_pnl_usdt), 2) as avg_pnl
            FROM demo_account
            WHERE ts > datetime('now', '-7 days')
            GROUP BY symbol, action
        """)
        demo_trades = [dict(r) for r in cur.fetchall()]

        # Recente events
        cur = conn.execute("""
            SELECT source, level, title, ts
            FROM events
            WHERE ts > datetime('now', '-24 hours')
            ORDER BY ts DESC
            LIMIT 20
        """)
        recent_events = [dict(r) for r in cur.fetchall()]

        conn.close()
        return {
            "signal_performance": signal_perf,
            "demo_trades": demo_trades,
            "recent_events": recent_events,
        }
    except Exception as e:
        log.error(f"DB stats fout: {e}")
        return {"signal_performance": [], "demo_trades": [], "recent_events": []}


def get_ohlcv_summary() -> dict:
    """Kort overzicht van opgeslagen OHLCV data per coin."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""
            SELECT symbol, interval, COUNT(*) as candles,
                   MIN(ts) as first_ts, MAX(ts) as last_ts
            FROM ohlcv_history
            GROUP BY symbol, interval
        """)
        rows = [dict(sqlite3.Row(cur, r)) for r in cur.fetchall()]
        conn.close()
        return {"ohlcv_coverage": rows}
    except Exception as e:
        return {"ohlcv_coverage": [], "error": str(e)}


# ── Kimi patroonanalyse ──────────────────────────────────────────────────────

def run_kimi_analysis() -> dict:
    """Nachtelijke Kimi analyse: patronen in signalen en prijsdata."""
    log.info("Start nachtelijke Kimi patroonanalyse...")

    stats = get_signal_stats()
    ohlcv_summary = get_ohlcv_summary()

    # Bereken huidige RSI en trend per coin
    coin_indicators = []
    for symbol in TRACKED_COINS:
        symbol = symbol.strip()
        if not symbol:
            continue
        try:
            df = fetch_ohlcv(symbol, "4h", limit=100)
            close = df["close"].values
            rsi_vals = calc_rsi(close)
            ema21 = calc_ema(close, 21)
            ema55 = calc_ema(close, 55)
            cur_rsi = float(rsi_vals[-1]) if not np.isnan(rsi_vals[-1]) else None
            cur_price = float(close[-1])
            trend = "bullish" if (ema21[-1] > ema55[-1] and not np.isnan(ema21[-1])) else "bearish"
            coin_indicators.append({
                "symbol": symbol,
                "price": round(cur_price, 4),
                "rsi_4h": round(cur_rsi, 1) if cur_rsi else None,
                "trend_4h": trend,
            })
        except Exception as e:
            log.error(f"Indicator fout {symbol}: {e}")

    prompt = f"""Je bent een crypto trading pattern analyst. Analyseer de volgende data van de afgelopen 7 dagen en identificeer patronen.

## Signaal Performance (afgelopen 7 dagen)
{json.dumps(stats['signal_performance'], indent=2)}

## Demo Trades
{json.dumps(stats['demo_trades'], indent=2)}

## Recente Events (24u)
{json.dumps(stats['recent_events'], indent=2)}

## Huidige Indicatoren (4h)
{json.dumps(coin_indicators, indent=2)}

## OHLCV Data Beschikbaarheid
{json.dumps(ohlcv_summary.get('ohlcv_coverage', []), indent=2)}

Geef je analyse in het volgende JSON formaat:
{{
  "patterns": [
    {{
      "type": "trend|reversal|correlation|anomaly|performance",
      "symbol": "COIN of ALL",
      "description": "Korte beschrijving",
      "confidence": 0.0-1.0,
      "impact": "low|medium|high",
      "recommendation": "Concrete aanbeveling"
    }}
  ],
  "overall_assessment": "Korte samenvatting van de marktsituatie",
  "risk_level": "low|medium|high",
  "suggested_actions": ["actie1", "actie2"]
}}

Focus op:
1. Welke signalen (BUY/SELL) het best presteren per coin
2. Onverwachte correlaties of divergenties
3. RSI patronen die kansen of risico's signaleren
4. Performance trends (verbetering of verslechtering)
5. Concrete aanbevelingen voor parameter aanpassingen

Antwoord ALLEEN met valid JSON, geen andere tekst."""

    if not KIMI_API_KEY:
        log.warning("Geen KIMI_API_KEY — skip analyse")
        return {"error": "KIMI_API_KEY niet geconfigureerd", "stats": stats, "indicators": coin_indicators}

    try:
        client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL)
        response = client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4096,
        )
        content = response.choices[0].message.content.strip()
        # Parse JSON uit response (strip eventuele markdown code blocks)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        analysis = json.loads(content)
        log.info(f"Kimi analyse compleet: {len(analysis.get('patterns', []))} patronen gevonden")
    except json.JSONDecodeError as e:
        log.error(f"Kimi response niet valid JSON: {e}")
        analysis = {"raw_response": content, "parse_error": str(e)}
    except Exception as e:
        log.error(f"Kimi API fout: {e}")
        analysis = {"error": str(e)}

    # Sla rapport op
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "analysis": analysis,
        "input_stats": stats,
        "indicators": coin_indicators,
    }

    report_path = f"{REPORT_DIR}/pattern_report_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        log.info(f"Rapport opgeslagen: {report_path}")
    except Exception as e:
        log.error(f"Rapport opslaan mislukt: {e}")

    # Telegram alert bij high impact bevindingen
    high_impact = [p for p in analysis.get("patterns", []) if p.get("impact") == "high"]
    if high_impact and TG_BOT_TOKEN and TG_CHAT_ID:
        alert_lines = ["🔍 <b>Kimi Pattern Alert</b>\n"]
        for p in high_impact[:3]:
            alert_lines.append(f"• <b>{p.get('symbol', '?')}</b>: {p.get('description', '?')}")
            alert_lines.append(f"  → {p.get('recommendation', '')}\n")
        alert_lines.append(f"Risico: {analysis.get('risk_level', '?')}")
        try:
            req.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": "\n".join(alert_lines), "parse_mode": "HTML"},
                timeout=10,
            )
            log.info("Telegram alert verzonden")
        except Exception as e:
            log.error(f"Telegram alert mislukt: {e}")

    return report


# ── Scheduler ─────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup():
    ensure_ohlcv_table()
    # OHLCV ophalen elke 4 uur
    scheduler.add_job(collect_all_ohlcv, "interval", hours=4, id="ohlcv_collect",
                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30))
    # Kimi analyse om ANALYSIS_HOUR UTC
    scheduler.add_job(run_kimi_analysis, "cron", hour=ANALYSIS_HOUR, minute=0, id="nightly_analysis")
    scheduler.start()
    log.info(f"Scheduler gestart: OHLCV elke 4u, Kimi analyse om {ANALYSIS_HOUR}:00 UTC")


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
    return {"status": "ok", "service": "kimi_pattern_agent", "scheduled_jobs": jobs}


@app.post("/collect")
def trigger_collect():
    """Handmatig OHLCV collectie triggeren."""
    collect_all_ohlcv()
    return {"ok": True, "message": "OHLCV collectie voltooid"}


@app.post("/analyze")
def trigger_analyze():
    """Handmatig Kimi analyse triggeren."""
    report = run_kimi_analysis()
    return {"ok": True, "report": report}


@app.get("/report/latest")
def latest_report():
    """Haal het meest recente rapport op."""
    import glob
    files = sorted(glob.glob(f"{REPORT_DIR}/pattern_report_*.json"), reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail="Geen rapporten gevonden")
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/report/{date}")
def report_by_date(date: str):
    """Haal rapport op voor specifieke datum (YYYY-MM-DD)."""
    path = f"{REPORT_DIR}/pattern_report_{date}.json"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Geen rapport voor {date}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/ohlcv/status")
def ohlcv_status():
    """Overzicht van opgeslagen OHLCV data."""
    return get_ohlcv_summary()


@app.get("/stats")
def signal_stats():
    """Signaal performance statistieken uit de DB."""
    return get_signal_stats()
