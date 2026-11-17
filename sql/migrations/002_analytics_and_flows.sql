-- Migration 002: analytical, institutional, risk and backtest data.
-- Additive only: preserves the existing stock_master, daily_prices,
-- import_runs, backfill_progress tables and all existing rows.
-- Apply after sql/schema.sql. All market data is keyed by market + stock_id.

CREATE TABLE IF NOT EXISTS data_ingestion_runs (
    ingestion_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset TEXT NOT NULL CHECK (dataset IN (
        'stock_master', 'daily_prices', 'institutional_flows', 'margin_short',
        'tdcc_distribution', 'insider_holdings', 'financial_statements'
    )),
    market TEXT CHECK (market IN ('twse', 'tpex')),
    stock_id VARCHAR(6),
    period_start DATE,
    period_end DATE,
    source TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    rows_received INTEGER NOT NULL DEFAULT 0 CHECK (rows_received >= 0),
    rows_upserted INTEGER NOT NULL DEFAULT 0 CHECK (rows_upserted >= 0),
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS daily_technicals (
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    trade_date DATE NOT NULL,
    ma5 NUMERIC(18,4), ma10 NUMERIC(18,4), ma13 NUMERIC(18,4),
    ma20 NUMERIC(18,4), ma34 NUMERIC(18,4), ma55 NUMERIC(18,4),
    ma60 NUMERIC(18,4), ma120 NUMERIC(18,4), ma240 NUMERIC(18,4),
    rsi14 NUMERIC(10,4),
    volume_ma5 NUMERIC(24,4), volume_ma20 NUMERIC(24,4),
    atr14 NUMERIC(18,4),
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, trade_date),
    FOREIGN KEY (market, stock_id, trade_date)
        REFERENCES daily_prices (market, stock_id, trade_date) ON DELETE CASCADE,
    CHECK (rsi14 IS NULL OR (rsi14 >= 0 AND rsi14 <= 100))
);
CREATE INDEX IF NOT EXISTS idx_daily_technicals_date
    ON daily_technicals (trade_date DESC);

CREATE TABLE IF NOT EXISTS smc_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    event_date DATE NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'BOS', 'CHOCH', 'ORDER_BLOCK', 'FVG', 'LIQUIDITY_SWEEP'
    )),
    direction TEXT CHECK (direction IN ('bullish', 'bearish', 'neutral')),
    zone_low NUMERIC(18,4),
    zone_high NUMERIC(18,4),
    reference_date DATE,
    confirmation_date DATE,
    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT,
    CHECK (zone_low IS NULL OR zone_high IS NULL OR zone_low <= zone_high)
);
CREATE INDEX IF NOT EXISTS idx_smc_events_stock_date
    ON smc_events (market, stock_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_smc_events_type_date
    ON smc_events (event_type, event_date DESC);

CREATE TABLE IF NOT EXISTS institutional_flows (
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    trade_date DATE NOT NULL,
    foreign_buy BIGINT, foreign_sell BIGINT, foreign_net BIGINT,
    trust_buy BIGINT, trust_sell BIGINT, trust_net BIGINT,
    dealer_buy BIGINT, dealer_sell BIGINT, dealer_net BIGINT,
    total_net BIGINT,
    source TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, trade_date),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_institutional_flows_date
    ON institutional_flows (trade_date DESC);

CREATE TABLE IF NOT EXISTS margin_short (
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    trade_date DATE NOT NULL,
    margin_buy BIGINT, margin_sell BIGINT, margin_repayment BIGINT,
    margin_balance BIGINT,
    short_sell BIGINT, short_buyback BIGINT, short_repayment BIGINT,
    short_balance BIGINT,
    margin_quota BIGINT, short_quota BIGINT,
    source TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, trade_date),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_margin_short_date
    ON margin_short (trade_date DESC);

CREATE TABLE IF NOT EXISTS tdcc_share_distribution (
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    as_of_date DATE NOT NULL,
    holder_range TEXT NOT NULL,
    holder_count BIGINT,
    share_count BIGINT,
    share_percent NUMERIC(9,4),
    source TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, as_of_date, holder_range),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT,
    CHECK (share_percent IS NULL OR (share_percent >= 0 AND share_percent <= 100))
);
CREATE INDEX IF NOT EXISTS idx_tdcc_distribution_date
    ON tdcc_share_distribution (as_of_date DESC);

CREATE TABLE IF NOT EXISTS insider_holdings (
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    as_of_date DATE NOT NULL,
    person_name TEXT NOT NULL,
    person_role TEXT NOT NULL,
    share_count BIGINT,
    share_percent NUMERIC(9,4),
    pledged_shares BIGINT,
    source TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, as_of_date, person_name, person_role),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT,
    CHECK (share_percent IS NULL OR (share_percent >= 0 AND share_percent <= 100))
);
CREATE INDEX IF NOT EXISTS idx_insider_holdings_date
    ON insider_holdings (as_of_date DESC);

CREATE TABLE IF NOT EXISTS financial_statements (
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter SMALLINT NOT NULL CHECK (fiscal_quarter BETWEEN 1 AND 4),
    statement_type TEXT NOT NULL CHECK (statement_type IN (
        'income', 'balance_sheet', 'cash_flow'
    )),
    currency TEXT NOT NULL DEFAULT 'TWD',
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL,
    published_at DATE,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, fiscal_year, fiscal_quarter, statement_type),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_financial_statements_period
    ON financial_statements (fiscal_year DESC, fiscal_quarter DESC);

CREATE TABLE IF NOT EXISTS analysis_signals (
    signal_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    signal_date DATE NOT NULL,
    strategy TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('short', 'swing', 'long')),
    signal TEXT NOT NULL CHECK (signal IN ('buy_watch', 'hold', 'reduce', 'avoid')),
    score NUMERIC(8,4),
    entry_price NUMERIC(18,4),
    stop_price NUMERIC(18,4),
    target_price NUMERIC(18,4),
    risk_per_share NUMERIC(18,4),
    rationale JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_analysis_signals_stock_date
    ON analysis_signals (market, stock_id, signal_date DESC);

CREATE TABLE IF NOT EXISTS backtest_runs (
    backtest_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital NUMERIC(20,2) NOT NULL CHECK (initial_capital > 0),
    max_risk_fraction NUMERIC(8,6) NOT NULL DEFAULT 0.01
        CHECK (max_risk_fraction > 0 AND max_risk_fraction <= 0.01),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'failed')),
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    CHECK (start_date <= end_date)
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    trade_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    backtest_id BIGINT NOT NULL REFERENCES backtest_runs (backtest_id) ON DELETE CASCADE,
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    entry_date DATE NOT NULL,
    exit_date DATE,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    entry_price NUMERIC(18,4) NOT NULL,
    exit_price NUMERIC(18,4),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    stop_price NUMERIC(18,4),
    fees NUMERIC(18,4) NOT NULL DEFAULT 0,
    slippage NUMERIC(18,4) NOT NULL DEFAULT 0,
    pnl NUMERIC(20,4),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT,
    CHECK (exit_date IS NULL OR entry_date <= exit_date)
);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
    ON backtest_trades (backtest_id, entry_date);

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    opened_at DATE NOT NULL,
    closed_at DATE,
    side TEXT NOT NULL DEFAULT 'long' CHECK (side IN ('long', 'short')),
    entry_price NUMERIC(18,4) NOT NULL,
    exit_price NUMERIC(18,4),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    initial_stop NUMERIC(18,4),
    risk_amount NUMERIC(20,4),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    notes TEXT,
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id) ON DELETE RESTRICT,
    CHECK (closed_at IS NULL OR opened_at <= closed_at)
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_status
    ON paper_positions (status, opened_at DESC);

-- TDCC ownership distribution is weekly; it is not a daily market series.
COMMENT ON TABLE tdcc_share_distribution IS
    'Weekly TDCC shareholder distribution snapshots; do not treat as daily data.';
COMMENT ON TABLE analysis_signals IS
    'Research signals only. This system does not submit or execute brokerage orders.';
COMMENT ON TABLE paper_positions IS
    'Paper-trading ledger only; no connection to broker order execution.';
