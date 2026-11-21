-- Research-only scope exclusion registry.
-- Apply explicitly after review to environments that do not yet have this table.
-- No historical price rows are deleted, updated, or reclassified.
CREATE TABLE IF NOT EXISTS public.model_stock_exclusions (
    market text NOT NULL CHECK (market IN ('twse','tpex')),
    stock_id varchar NOT NULL,
    reason text NOT NULL,
    excluded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (market, stock_id)
);

-- User-approved issuer exclusion; idempotent and append-only.
INSERT INTO public.model_stock_exclusions (market,stock_id,reason)
VALUES ('twse','1589','User-requested exclusion from current research, historical backfill, and model validation')
ON CONFLICT (market,stock_id) DO NOTHING;
