-- First capture only: never UPDATE or DELETE a score-date's frozen roster.
-- The timestamp is assigned by PostgreSQL server clock, never user-supplied.
-- Research precommit only. Real forward outcomes are not stored here.
CREATE TABLE IF NOT EXISTS public.research_forward_frozen_cohorts (
  model_version VARCHAR(90) NOT NULL,
  signal_date DATE NOT NULL,
  frozen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  model_sha256 CHAR(64) NOT NULL,
  cohort_sha256 CHAR(64) NOT NULL,
  universe_count INTEGER NOT NULL CHECK (universe_count BETWEEN 50 AND 2500),
  selected_count INTEGER NOT NULL CHECK (selected_count BETWEEN 1 AND 500),
  roster JSONB NOT NULL,
  PRIMARY KEY (model_version,signal_date),
  CHECK (jsonb_typeof(roster)='array'),
  CHECK (jsonb_array_length(roster)=universe_count),
  CHECK ((frozen_at AT TIME ZONE 'Asia/Taipei')::date >= signal_date)
);

-- Defense in depth: the writer SQL already uses INSERT/DO NOTHING, but
-- database-side triggers also refuse UPDATE and DELETE of every sealed date.
-- A future human review can still inspect the exact original roster.
CREATE OR REPLACE FUNCTION public.block_frozen_research_rewrite()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Prospective model cohort is immutable; UPDATE/DELETE denied';
END;
$$;
CREATE OR REPLACE TRIGGER block_frozen_research_update_delete
BEFORE UPDATE OR DELETE ON public.research_forward_frozen_cohorts
FOR EACH ROW EXECUTE FUNCTION public.block_frozen_research_rewrite();
