-- First-observed snapshot of official TWSE/TPEx general-industry balance sheets.
-- No issuer-specific historical published_at can be derived from table date.
-- No model or trading signal consumes these fields automatically.
CREATE TABLE IF NOT EXISTS public.official_balance_sheet_observations (
  market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
  stock_id VARCHAR(6) NOT NULL,
  fiscal_year INTEGER NOT NULL CHECK (fiscal_year BETWEEN 2000 AND 2100),
  fiscal_quarter SMALLINT NOT NULL CHECK (fiscal_quarter BETWEEN 1 AND 4),
  period_end DATE NOT NULL,
  official_table_date DATE,
  assets_thousands_ntd NUMERIC(24,3) NOT NULL CHECK (assets_thousands_ntd > 0),
  liabilities_thousands_ntd NUMERIC(24,3) NOT NULL CHECK (liabilities_thousands_ntd >= 0),
  equity_thousands_ntd NUMERIC(24,3) NOT NULL,
  current_assets_thousands_ntd NUMERIC(24,3),
  current_liabilities_thousands_ntd NUMERIC(24,3),
  parent_equity_thousands_ntd NUMERIC(24,3),
  accounting_identity_verified BOOLEAN NOT NULL,
  first_observed_at TIMESTAMPTZ NOT NULL,
  source_url TEXT NOT NULL,
  payload_sha256 CHAR(64) NOT NULL,
  PRIMARY KEY (market,stock_id,period_end,payload_sha256),
  CHECK (period_end <= (first_observed_at AT TIME ZONE 'Asia/Taipei')::date),
  CHECK (official_table_date IS NULL OR
        (official_table_date >= period_end AND
         official_table_date <= (first_observed_at AT TIME ZONE 'Asia/Taipei')::date))
);
CREATE INDEX IF NOT EXISTS official_balance_first_observed_lookup
 ON public.official_balance_sheet_observations
 (market,stock_id,period_end,first_observed_at);
CREATE OR REPLACE FUNCTION public.reject_official_balance_rewrite()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Official first-observed balance-sheet versions are immutable';
END;
$$;
CREATE OR REPLACE TRIGGER official_balance_immutable
BEFORE UPDATE OR DELETE ON public.official_balance_sheet_observations
FOR EACH ROW EXECUTE FUNCTION public.reject_official_balance_rewrite();
