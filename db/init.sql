-- OpenClaw Apex — PostgreSQL Schema
-- Migratie vanuit SQLite, alle tabellen + nieuwe tabellen voor pattern agent

-- ══════════════════════════════════════════════════════════════════════════════
-- Core trading
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS events (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source      TEXT NOT NULL,
    level       TEXT NOT NULL,
    title       TEXT NOT NULL,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executor    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    size        TEXT NOT NULL,
    price       REAL,
    raw_json    TEXT
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Proposals
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS proposals (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent       TEXT NOT NULL,
    params_json TEXT NOT NULL,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS proposals_v2 (
    id              TEXT PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    type            TEXT NOT NULL,
    payload_json    TEXT NOT NULL DEFAULT '{}',
    reason          TEXT NOT NULL DEFAULT '',
    requested_by    TEXT NOT NULL DEFAULT 'unknown',
    requires_confirm INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending',
    confirmed_at    TIMESTAMPTZ,
    applied_at      TIMESTAMPTZ
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Signal tracking
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS signal_performance (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT NOT NULL,
    signal          TEXT NOT NULL,
    active_signals  TEXT,
    entry_price     REAL NOT NULL,
    price_15m       REAL,
    price_1h        REAL,
    price_4h        REAL,
    pnl_15m_pct     REAL,
    pnl_1h_pct      REAL,
    pnl_4h_pct      REAL,
    status          TEXT DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS historical_backtest (
    id              SERIAL PRIMARY KEY,
    run_ts          TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    interval        TEXT NOT NULL,
    months          INTEGER NOT NULL,
    candle_ts       TIMESTAMPTZ NOT NULL,
    signal          TEXT NOT NULL,
    active_signals  TEXT,
    entry_price     REAL NOT NULL,
    price_1h        REAL,
    price_4h        REAL,
    price_24h       REAL,
    pnl_1h_pct      REAL,
    pnl_4h_pct      REAL,
    pnl_24h_pct     REAL
);

CREATE TABLE IF NOT EXISTS market_context (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT NOT NULL,
    signal          TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    rsi_5m          REAL,
    tf_confirm_score INTEGER,
    tf_bias         TEXT,
    tf_1h_rsi       REAL,
    tf_4h_rsi       REAL,
    outcome_1h_pct  REAL,
    outcome_4h_pct  REAL,
    status          TEXT DEFAULT 'open'
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Demo account
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS demo_account (
    id                  SERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol              TEXT NOT NULL,
    action              TEXT NOT NULL,
    price               REAL NOT NULL,
    virtual_size_usdt   REAL NOT NULL,
    virtual_pnl_usdt    REAL DEFAULT 0,
    balance_after       REAL NOT NULL,
    signal              TEXT,
    note                TEXT
);

CREATE TABLE IF NOT EXISTS demo_balance (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    balance         REAL NOT NULL DEFAULT 1000.0,
    peak_balance    REAL NOT NULL DEFAULT 1000.0,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    total_volume_usdt REAL DEFAULT 0
);

-- Seed demo balance als die nog niet bestaat
INSERT INTO demo_balance (id, balance, peak_balance) VALUES (1, 1000.0, 1000.0)
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════
-- Price & market data
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS price_snapshots (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol      TEXT NOT NULL,
    price       REAL NOT NULL,
    rsi         REAL,
    volume_usdt REAL,
    signal      TEXT,
    change_pct  REAL,
    atr         REAL,
    tf_bias     TEXT
);

CREATE TABLE IF NOT EXISTS crash_score_log (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol      TEXT NOT NULL,
    score       REAL NOT NULL,
    ob_pct      REAL,
    vol_pct     REAL,
    rsi_pct     REAL,
    mom_pct     REAL
);

CREATE TABLE IF NOT EXISTS exchange_consensus_log (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT NOT NULL,
    consensus       REAL,
    coinbase_price  REAL,
    binance_price   REAL,
    bybit_price     REAL,
    okx_price       REAL,
    kraken_price    REAL,
    blofin_price    REAL,
    divergence_pct  REAL,
    coinbase_lead   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS market_events (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type      TEXT NOT NULL,
    symbol          TEXT,
    severity        TEXT,
    value           REAL,
    description     TEXT,
    payload_json    TEXT
);

-- ══════════════════════════════════════════════════════════════════════════════
-- OHLCV historische data (kimi_pattern_agent)
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ohlcv_history (
    symbol      TEXT NOT NULL,
    interval    TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    UNIQUE(symbol, interval, ts)
);

CREATE TABLE IF NOT EXISTS pattern_reports (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    report_date DATE NOT NULL UNIQUE,
    analysis    JSONB,
    input_stats JSONB,
    indicators  JSONB
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Auth (Command Center + control_api)
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS otp_codes (
    email       TEXT NOT NULL,
    code        TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Indices voor performance
-- ══════════════════════════════════════════════════════════════════════════════

-- ══════════════════════════════════════════════════════════════════════════════
-- TestBot paper trading
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS testbot_trades (
    id          SERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    signal      TEXT,
    setup_score INTEGER,
    entry_price NUMERIC(20,8) NOT NULL,
    entry_ts    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    stake_usd   NUMERIC(10,2) DEFAULT 100.0,
    tp_pct      NUMERIC(6,3)  DEFAULT 4.5,
    sl_pct      NUMERIC(6,3)  DEFAULT 2.0,
    tp_price    NUMERIC(20,8),
    sl_price    NUMERIC(20,8),
    price_15m   NUMERIC(20,8),
    price_1h    NUMERIC(20,8),
    price_2h    NUMERIC(20,8),
    close_price NUMERIC(20,8),
    close_ts    TIMESTAMPTZ,
    close_reason TEXT,
    pnl_pct     NUMERIC(10,4),
    pnl_usd     NUMERIC(10,4),
    fee_usd     NUMERIC(10,4),
    net_pnl_usd NUMERIC(10,4),
    status      TEXT NOT NULL DEFAULT 'open'
);

-- ══════════════════════════════════════════════════════════════════════════════
-- Feature store — indicator snapshot op entry per demo trade
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS trade_features (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    demo_trade_id   INTEGER,                -- FK naar demo_account.id
    symbol          TEXT NOT NULL,
    signal          TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    -- Technische indicators op entry
    rsi             REAL,
    macd_hist       REAL,
    adx             REAL,
    bb_width        REAL,
    -- EMA niveaus en afstand tot prijs
    ema21           REAL,
    ema55           REAL,
    ema200          REAL,
    ema21_dist_pct  REAL,                   -- (price - ema21) / ema21 * 100
    ema55_dist_pct  REAL,
    ema200_dist_pct REAL,
    -- Marktcondities
    crash_score     REAL,
    volume_usdt     REAL,
    atr             REAL,
    -- Multi-timeframe context
    tf_bias         TEXT,
    tf_confirm_score INTEGER,
    -- Regime (bull/bear/chop) op basis van BTC EMA200 4h
    btc_regime      TEXT,
    btc_ema200      REAL,
    btc_close       REAL,
    -- Blocker context — welke filters gingen over? (JSON)
    blocker_context TEXT,
    -- Uitkomsten — gevuld nadat trade sluit
    pnl_1h_pct      REAL,
    pnl_4h_pct      REAL,
    outcome_status  TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_trade_features_symbol ON trade_features(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_features_ts ON trade_features(ts);
CREATE INDEX IF NOT EXISTS idx_trade_features_signal ON trade_features(signal);
CREATE INDEX IF NOT EXISTS idx_trade_features_demo_id ON trade_features(demo_trade_id);

CREATE INDEX IF NOT EXISTS idx_testbot_status ON testbot_trades(status);
CREATE INDEX IF NOT EXISTS idx_testbot_symbol ON testbot_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_testbot_ts     ON testbot_trades(entry_ts);

CREATE TABLE IF NOT EXISTS short_positions (
    id                  SERIAL PRIMARY KEY,
    ts_entry            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts_exit             TIMESTAMPTZ,
    symbol              TEXT NOT NULL,
    entry_price         REAL NOT NULL,
    exit_price          REAL,
    size_usdt           REAL NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',
    exit_reason         TEXT,
    pnl_pct             REAL,
    duration_s          INTEGER,
    mae_pct             REAL,
    mfe_pct             REAL,
    trigger_delta       REAL,
    trigger_vol_ratio   REAL,
    trigger_spread_bps  REAL,
    trigger_mode        TEXT
);
CREATE INDEX IF NOT EXISTS idx_short_pos_status ON short_positions(status);
CREATE INDEX IF NOT EXISTS idx_short_pos_ts     ON short_positions(ts_entry DESC);

CREATE TABLE IF NOT EXISTS short_log (
    id      SERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol  TEXT NOT NULL,
    action  TEXT NOT NULL,
    reason  TEXT,
    price   REAL,
    pnl_pct REAL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_short_log_ts ON short_log(ts DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol      TEXT NOT NULL,
    kind        TEXT NOT NULL,     -- spike | drop | short_signal | mode_switch
    severity    TEXT NOT NULL,     -- minor | major | extreme
    message     TEXT,
    price       REAL,
    delta_pct   REAL,
    vol_ratio   REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts       ON alerts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol   ON alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);

CREATE TABLE IF NOT EXISTS mode_log (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mode_from   TEXT NOT NULL,
    mode_to     TEXT NOT NULL,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_mode_log_ts ON mode_log(ts DESC);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_signal_perf_ts ON signal_performance(ts);
CREATE INDEX IF NOT EXISTS idx_signal_perf_symbol ON signal_performance(symbol);
CREATE INDEX IF NOT EXISTS idx_demo_account_ts ON demo_account(ts);
CREATE INDEX IF NOT EXISTS idx_price_snapshots_ts ON price_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_crash_score_ts ON crash_score_log(ts);
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_interval ON ohlcv_history(symbol, interval);
CREATE INDEX IF NOT EXISTS idx_market_events_ts ON market_events(ts);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_v2_status ON proposals_v2(status);

-- ── Universe Coins ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS universe_coins (
    id                      SERIAL PRIMARY KEY,
    symbol                  TEXT NOT NULL UNIQUE,
    name                    TEXT,
    rank                    INTEGER,
    market_cap_usd          BIGINT,
    volume_24h_usd          BIGINT,
    is_stablecoin           BOOLEAN DEFAULT FALSE,
    active_for_trading      BOOLEAN DEFAULT TRUE,
    active_for_monitoring   BOOLEAN DEFAULT TRUE,
    data_quality_score      REAL DEFAULT 0.0,
    source                  TEXT,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_universe_rank   ON universe_coins(rank);
CREATE INDEX IF NOT EXISTS idx_universe_active ON universe_coins(active_for_trading);
CREATE INDEX IF NOT EXISTS idx_universe_stable ON universe_coins(is_stablecoin);

CREATE TABLE IF NOT EXISTS universe_history (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    coins_json  TEXT,
    source      TEXT,
    rank_count  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_universe_history_ts ON universe_history(ts DESC);

-- ── Near-Miss Log ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS near_miss_log (
    id                 BIGSERIAL PRIMARY KEY,
    ts_utc             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol             VARCHAR(20) NOT NULL,
    event_kind         VARCHAR(30) NOT NULL,
    mode_at_time       VARCHAR(10) NOT NULL DEFAULT 'normal',
    price_delta_15s    REAL,
    price_delta_60s    REAL,
    price_delta_90s    REAL,
    volume_ratio       REAL,
    spread_bps         REAL,
    slippage_bps       REAL,
    passed_guards      TEXT,
    failed_guard       TEXT,
    failed_reason      TEXT,
    severity_candidate VARCHAR(10),
    correlation_id     TEXT
);
CREATE INDEX IF NOT EXISTS idx_nm_ts   ON near_miss_log(ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_nm_sym  ON near_miss_log(symbol);
CREATE INDEX IF NOT EXISTS idx_nm_kind ON near_miss_log(event_kind);
