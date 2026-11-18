-- Transparent composite chip score; source tables remain unchanged.
CREATE TABLE IF NOT EXISTS daily_chip_scores (
  market TEXT NOT NULL,
  stock_id VARCHAR(6) NOT NULL,
  as_of_date DATE NOT NULL,
  total_score NUMERIC(6,2),
  coverage_weight NUMERIC(4,2) NOT NULL DEFAULT 0,
  institutional_score NUMERIC(6,2),
  margin_score NUMERIC(6,2),
  tdcc_score NUMERIC(6,2),
  insider_score NUMERIC(6,2),
  component_status JSONB NOT NULL DEFAULT '{}'::jsonb,
  calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (market, stock_id, as_of_date),
  FOREIGN KEY (market, stock_id) REFERENCES stock_master(market, stock_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CHECK (total_score IS NULL OR (total_score >= 0 AND total_score <= 100)),
  CHECK (coverage_weight >= 0 AND coverage_weight <= 1)
);
CREATE INDEX IF NOT EXISTS idx_daily_chip_scores_stock_date
  ON daily_chip_scores(stock_id, as_of_date DESC);
