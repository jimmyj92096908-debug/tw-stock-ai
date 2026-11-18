-- Persistent rotation state for incremental full-market daily refresh.
CREATE TABLE IF NOT EXISTS market_data_refresh_state (
    market TEXT NOT NULL CHECK (market IN ('twse', 'tpex')),
    stock_id VARCHAR(6) NOT NULL,
    last_attempt_at TIMESTAMPTZ,
    last_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (last_status IN ('pending', 'success', 'failed')),
    latest_trade_date DATE,
    rows_downloaded INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
