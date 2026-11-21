-- Official exchange snapshots: first observed time != issuer disclosure time.
-- Revisions append rows and cannot overwrite existing (market,symbol,month,hash).
-- No factor model, LINE or trading writes use this table.
CREATE TABLE IF NOT EXISTS public.official_revenue_observations (
  market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
  stock_id VARCHAR(6) NOT NULL,
  period_end DATE NOT NULL,
  reported_revenue_thousands_ntd NUMERIC(22,3) NOT NULL,
  reported_yoy_pct NUMERIC(12,5),
  official_table_date DATE NOT NULL,
  first_observed_at TIMESTAMPTZ NOT NULL,
  source_url TEXT NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  PRIMARY KEY (market,stock_id,period_end,payload_sha256),
  CHECK (period_end<=official_table_date),
  CHECK (official_table_date<= (first_observed_at AT TIME ZONE 'Asia/Taipei')::date)
);
CREATE INDEX IF NOT EXISTS official_revenue_asof_lookup
ON public.official_revenue_observations(market,stock_id,period_end,first_observed_at);
