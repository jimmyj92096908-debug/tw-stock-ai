-- Durable progress records for historical backfill batches.
-- Safe to apply repeatedly; this migration only creates a new table and index.

CREATE TABLE IF NOT EXISTS backfill_progress (
    market TEXT NOT NULL CHECK (market IN ('twse', 'tpex')),
    stock_id VARCHAR(6) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows_downloaded INTEGER NOT NULL DEFAULT 0 CHECK (rows_downloaded >= 0),
    first_trade_date DATE,
    last_trade_date DATE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    github_run_id TEXT,
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id, start_date, end_date),
    CHECK (start_date <= end_date)
);

CREATE INDEX IF NOT EXISTS idx_backfill_progress_status
    ON backfill_progress (status, market, stock_id);

COMMENT ON TABLE backfill_progress IS
    'Durable per-stock historical backfill status; success is recorded only after Neon row verification.';
