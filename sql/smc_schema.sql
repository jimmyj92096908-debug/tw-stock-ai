-- Additive migration: run once against the Neon database.
CREATE TABLE IF NOT EXISTS daily_smc (
    market TEXT NOT NULL CHECK (market IN ('twse', 'tpex')),
    stock_id VARCHAR(6) NOT NULL,
    trade_date DATE NOT NULL,
    swing_high NUMERIC(18,4),
    swing_low NUMERIC(18,4),
    bos_bullish BOOLEAN NOT NULL DEFAULT FALSE,
    bos_bearish BOOLEAN NOT NULL DEFAULT FALSE,
    choch_bullish BOOLEAN NOT NULL DEFAULT FALSE,
    choch_bearish BOOLEAN NOT NULL DEFAULT FALSE,
    trend_direction SMALLINT NOT NULL DEFAULT 0 CHECK (trend_direction IN (-1,0,1)),
    liquidity_sweep_high BOOLEAN NOT NULL DEFAULT FALSE,
    liquidity_sweep_low BOOLEAN NOT NULL DEFAULT FALSE,
    order_block_type TEXT CHECK (order_block_type IN ('bullish','bearish')),
    order_block_high NUMERIC(18,4),
    order_block_low NUMERIC(18,4),
    fvg_type TEXT CHECK (fvg_type IN ('bullish','bearish')),
    fvg_high NUMERIC(18,4),
    fvg_low NUMERIC(18,4),
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, trade_date),
    FOREIGN KEY (market, stock_id, trade_date)
        REFERENCES daily_prices (market, stock_id, trade_date)
        ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_daily_smc_stock_date
    ON daily_smc (market, stock_id, trade_date DESC);
