-- The current general-industry income OpenAPI is a latest-quarter
-- snapshot, not a verified historical issuer filing timestamp.
-- EPS is year-to-date cumulative as reported, NOT one standalone quarter.
CREATE TABLE IF NOT EXISTS public.official_quarterly_income_observations (
 market TEXT NOT NULL CHECK (market IN ('twse','tpex')),
 stock_id VARCHAR(6) NOT NULL,
 fiscal_year INTEGER NOT NULL CHECK (fiscal_year BETWEEN 2000 AND 2100),
 fiscal_quarter SMALLINT NOT NULL CHECK (fiscal_quarter BETWEEN 1 AND 4),
 period_end DATE NOT NULL,
 official_table_date DATE,
 revenue_ytd_thousands_ntd NUMERIC(22,3),
 operating_income_ytd_thousands_ntd NUMERIC(22,3),
 net_income_ytd_thousands_ntd NUMERIC(22,3),
 basic_eps_ytd_ntd NUMERIC(16,6),
 eps_outlier_suppressed BOOLEAN NOT NULL DEFAULT FALSE,
 first_observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 source_url TEXT NOT NULL,
 payload_sha256 CHAR(64) NOT NULL,
 PRIMARY KEY (market,stock_id,period_end,payload_sha256),
 CHECK (official_table_date IS NULL OR
        (official_table_date>=period_end AND
         official_table_date<=(first_observed_at AT TIME ZONE 'Asia/Taipei')::date)),
 CHECK (period_end<=(first_observed_at AT TIME ZONE 'Asia/Taipei')::date),
 CHECK (revenue_ytd_thousands_ntd IS NOT NULL OR
        operating_income_ytd_thousands_ntd IS NOT NULL OR
        net_income_ytd_thousands_ntd IS NOT NULL OR
        basic_eps_ytd_ntd IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS quarterly_income_first_seal_lookup
 ON public.official_quarterly_income_observations
 (market,stock_id,period_end,first_observed_at);

CREATE OR REPLACE FUNCTION public.reject_quarterly_income_rewrite()
 RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Official first-observed quarterly source versions are immutable';
END;
$$;
CREATE OR REPLACE TRIGGER quarterly_income_immutable
BEFORE UPDATE OR DELETE ON public.official_quarterly_income_observations
FOR EACH ROW EXECUTE FUNCTION public.reject_quarterly_income_rewrite();
