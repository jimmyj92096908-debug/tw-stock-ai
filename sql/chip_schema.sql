-- Additive migration for official-source chip / ownership datasets.
-- Share quantities use shares (股). Raw source fields are retained for audit.
CREATE TABLE IF NOT EXISTS institutional_daily (
 market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
 stock_id VARCHAR(6) NOT NULL, trade_date DATE NOT NULL,
 foreign_buy BIGINT, foreign_sell BIGINT, foreign_net BIGINT,
 trust_buy BIGINT, trust_sell BIGINT, trust_net BIGINT,
 dealer_buy BIGINT, dealer_sell BIGINT, dealer_net BIGINT, total_net BIGINT,
 source TEXT NOT NULL, raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (market,stock_id,trade_date)
);
CREATE INDEX IF NOT EXISTS idx_institutional_daily_date ON institutional_daily (trade_date DESC,market,stock_id);

CREATE TABLE IF NOT EXISTS margin_daily (
 market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
 stock_id VARCHAR(6) NOT NULL, trade_date DATE NOT NULL,
 margin_buy BIGINT, margin_sell BIGINT, margin_cash_repay BIGINT, margin_balance BIGINT,
 short_buy BIGINT, short_sell BIGINT, short_stock_repay BIGINT, short_balance BIGINT,
 margin_limit BIGINT, short_limit BIGINT,
 source TEXT NOT NULL, raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (market,stock_id,trade_date)
);
CREATE INDEX IF NOT EXISTS idx_margin_daily_date ON margin_daily (trade_date DESC,market,stock_id);

CREATE TABLE IF NOT EXISTS tdcc_distribution_weekly (
 stock_id VARCHAR(6) NOT NULL, report_date DATE NOT NULL, holding_level TEXT NOT NULL,
 holder_count BIGINT, share_count BIGINT, inventory_ratio NUMERIC(9,4),
 source TEXT NOT NULL DEFAULT 'TDCC', raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (stock_id,report_date,holding_level)
);
CREATE INDEX IF NOT EXISTS idx_tdcc_distribution_date ON tdcc_distribution_weekly (report_date DESC,stock_id);

CREATE TABLE IF NOT EXISTS insider_holdings (
 market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
 stock_id VARCHAR(6) NOT NULL, report_month DATE NOT NULL,
 person_name TEXT NOT NULL, position_title TEXT,
 shares_held BIGINT, shares_pledged BIGINT,
 source TEXT NOT NULL, raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (market,stock_id,report_month,person_name,position_title)
);
CREATE INDEX IF NOT EXISTS idx_insider_holdings_date ON insider_holdings (report_month DESC,market,stock_id);
