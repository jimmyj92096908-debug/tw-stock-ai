-- Small append-only (one per calendar week) snapshots of the CURRENT
-- official TWSE and TPEx basic-company listing feeds.
-- NOT a historical listing/delisting or backtest eligible-date table.
-- PostgreSQL server assigns the first persisted timestamp.
CREATE TABLE IF NOT EXISTS public.official_issuer_weekly_snapshots (
    observed_week DATE PRIMARY KEY,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    payload_sha256 CHAR(64) NOT NULL,
    snapshot JSONB NOT NULL,
    CHECK (jsonb_typeof(snapshot)='object'),
    CHECK (snapshot->>'payload_sha256'=btrim(payload_sha256)),
    CHECK ((observed_at AT TIME ZONE 'Asia/Taipei')::date >= observed_week)
);
CREATE OR REPLACE FUNCTION public.block_official_issuer_snapshot_changes()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Immutable official observed issuer snapshot: UPDATE/DELETE denied';
END;
$$;
CREATE OR REPLACE TRIGGER block_official_issuer_weekly_update_delete
BEFORE UPDATE OR DELETE ON public.official_issuer_weekly_snapshots
FOR EACH ROW EXECUTE FUNCTION public.block_official_issuer_snapshot_changes();
