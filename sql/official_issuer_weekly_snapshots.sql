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

-- Never UPDATE the 2026-11-21 first observed unparsed TPEx snapshot.
-- A corrected official-field extractor can ONLY append a contemporaneous,
-- hash-linked correction. This preserves original evidence and auditability.
CREATE TABLE IF NOT EXISTS public.official_issuer_snapshot_corrections (
    observed_week DATE NOT NULL REFERENCES public.official_issuer_weekly_snapshots(observed_week),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    supersedes_sha256 CHAR(64) NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    snapshot JSONB NOT NULL,
    PRIMARY KEY (observed_week,payload_sha256),
    CHECK (jsonb_typeof(snapshot)='object'),
    CHECK (snapshot->>'payload_sha256'=btrim(payload_sha256)),
    CHECK (payload_sha256<>supersedes_sha256)
);
CREATE OR REPLACE TRIGGER block_official_issuer_corrections_update_delete
BEFORE UPDATE OR DELETE ON public.official_issuer_snapshot_corrections
FOR EACH ROW EXECUTE FUNCTION public.block_official_issuer_snapshot_changes();
