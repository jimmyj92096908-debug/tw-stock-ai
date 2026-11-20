-- MANUAL/EXPLICIT AUTHORIZATION ONLY.
-- Restore the exact pre-grant baseline of zero chip-table SELECT columns.
-- This rollback is scoped solely to the seven columns granted by
-- sql/line_chip_reader_column_grant.sql. No production automation calls it.
BEGIN;
DO $guard$
BEGIN
    IF current_database() <> 'twstock'
       OR to_regclass('public.daily_chip_scores') IS NULL
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='line_stock_reader')
    THEN
        RAISE EXCEPTION 'Wrong environment; refusing rollback';
    END IF;
    -- If broad access appeared since activation, stop and review it instead of
    -- falsely claiming seven column REVOKEs would restore least privilege.
    IF has_table_privilege('line_stock_reader','public.daily_chip_scores','SELECT') THEN
        RAISE EXCEPTION 'Unexpected table-wide SELECT; manual security review needed';
    END IF;
END
$guard$;

REVOKE SELECT (
  market, stock_id, as_of_date, total_score, coverage_weight,
  institutional_score, margin_score
) ON TABLE public.daily_chip_scores FROM line_stock_reader;

DO $verify$
DECLARE
    unexpected integer;
BEGIN
    SELECT count(*) INTO unexpected FROM information_schema.columns
    WHERE table_schema='public' AND table_name='daily_chip_scores'
      AND has_column_privilege(
        'line_stock_reader','public.daily_chip_scores',column_name,'SELECT'
      );
    IF unexpected <> 0
       OR has_any_column_privilege(
         'line_stock_reader','public.line_messages','SELECT')
    THEN
      RAISE EXCEPTION 'Rollback check failed; reviewing access state required';
    END IF;
END
$verify$;
COMMIT;
