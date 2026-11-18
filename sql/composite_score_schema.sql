-- Additive daily composite score schema and horizon-score migration.
CREATE TABLE IF NOT EXISTS daily_composite_scores (
 market TEXT NOT NULL,
 stock_id VARCHAR(6) NOT NULL,
 as_of_date DATE NOT NULL,
 total_score NUMERIC(6,2),
 coverage_weight NUMERIC(4,2) NOT NULL DEFAULT 0,
 technical_score NUMERIC(6,2),
 smc_score NUMERIC(6,2),
 chip_score NUMERIC(6,2),
 short_term_score NUMERIC(6,2),
 swing_score NUMERIC(6,2),
 long_term_score NUMERIC(6,2),
 short_coverage NUMERIC(4,2) NOT NULL DEFAULT 0,
 swing_coverage NUMERIC(4,2) NOT NULL DEFAULT 0,
 long_coverage NUMERIC(4,2) NOT NULL DEFAULT 0,
 component_status JSONB NOT NULL DEFAULT '{}'::jsonb,
 calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY (market,stock_id,as_of_date),
 FOREIGN KEY (market,stock_id) REFERENCES stock_master(market,stock_id)
 ON UPDATE CASCADE ON DELETE RESTRICT,
 CHECK (total_score IS NULL OR total_score BETWEEN 0 AND 100),
 CHECK (coverage_weight BETWEEN 0 AND 1)
);
ALTER TABLE daily_composite_scores ADD COLUMN IF NOT EXISTS short_term_score NUMERIC(6,2);
ALTER TABLE daily_composite_scores ADD COLUMN IF NOT EXISTS swing_score NUMERIC(6,2);
ALTER TABLE daily_composite_scores ADD COLUMN IF NOT EXISTS long_term_score NUMERIC(6,2);
ALTER TABLE daily_composite_scores ADD COLUMN IF NOT EXISTS short_coverage NUMERIC(4,2) NOT NULL DEFAULT 0;
ALTER TABLE daily_composite_scores ADD COLUMN IF NOT EXISTS swing_coverage NUMERIC(4,2) NOT NULL DEFAULT 0;
ALTER TABLE daily_composite_scores ADD COLUMN IF NOT EXISTS long_coverage NUMERIC(4,2) NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_daily_composite_scores_stock_date
 ON daily_composite_scores(stock_id,as_of_date DESC);
