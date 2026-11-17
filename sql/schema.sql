-- AI Taiwan Stock System: PostgreSQL schema for historical market data.
-- Apply once to a Neon PostgreSQL database. All timestamps use timestamptz.

CREATE TABLE IF NOT EXISTS stock_master (
    market TEXT NOT NULL CHECK (market IN ('twse', 'tpex')),
    stock_id VARCHAR(6) NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    market TEXT NOT NULL CHECK (market IN ('twse', 'tpex')),
    stock_id VARCHAR(6) NOT NULL,
    trade_date DATE NOT NULL,
    open NUMERIC(18, 4),
    high NUMERIC(18, 4),
    low NUMERIC(18, 4),
    close NUMERIC(18, 4),
    volume BIGINT,
    turnover NUMERIC(24, 2),
    price_change NUMERIC(18, 4),
    transactions BIGINT,
    source TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, trade_date),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (volume IS NULL OR volume >= 0),
    CHECK (transactions IS NULL OR transactions >= 0)
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_stock_date
    ON daily_prices (stock_id, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_prices_date
    ON daily_prices (trade_date DESC);

CREATE TABLE IF NOT EXISTS import_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market TEXT NOT NULL CHECK (market IN ('twse', 'tpex')),
    stock_id VARCHAR(6) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    rows_received INTEGER NOT NULL DEFAULT 0,
    rows_upserted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    error_message TEXT
);

-- Existing collectors report volume as shares (not lots).
COMMENT ON COLUMN daily_prices.volume IS 'Trading volume in shares, as returned by TWSE/TPEx source';
COMMENT ON COLUMN daily_prices.turnover IS 'Trading value in TWD';
