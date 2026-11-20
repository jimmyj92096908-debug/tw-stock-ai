-- MANUAL/EXPLICIT AUTHORIZATION ONLY.
-- NEVER executed by any GitHub CI job against Neon.
-- This file is for a separately authorized, reviewed owner-credential
-- session connected to the production twstock database.
-- It changes privileges only, not score rows, LINE settings or personal data.
BEGIN;

DO $guard$
DECLARE
    expected text[] := ARRAY[
      'as_of_date','coverage_weight','institutional_score','margin_score',
      'market','stock_id','total_score'
    ];
    invalid_count integer;
BEGIN
    IF current_database() <> 'twstock' THEN
      RAISE EXCEPTION 'Wrong database; refusing LINE chip grant';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM pg_roles
      WHERE rolname='line_stock_reader' AND rolcanlogin
        AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
        AND NOT rolbypassrls
    ) THEN
      RAISE EXCEPTION 'Dedicated unprivileged LINE reader role missing';
    END IF;
    IF to_regclass('public.daily_chip_scores') IS NULL
       OR to_regclass('public.line_messages') IS NULL
       OR NOT has_schema_privilege('line_stock_reader','public','USAGE') THEN
      RAISE EXCEPTION 'Required table/schema missing';
    END IF;

    SELECT count(*) INTO invalid_count FROM unnest(expected) AS col(name)
    WHERE NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name='daily_chip_scores'
        AND column_name=col.name
    );
    IF invalid_count <> 0 THEN
      RAISE EXCEPTION 'Required chip score column missing';
    END IF;

    -- Before the grant the exact seven fields must NOT already be granted.
    -- This ensures that the rollback plan can restore the original state.
    SELECT count(*) INTO invalid_count FROM unnest(expected) AS col(name)
    WHERE has_column_privilege(
      'line_stock_reader','public.daily_chip_scores',col.name,'SELECT'
    );
    IF invalid_count <> 0 THEN
      RAISE EXCEPTION 'Reader chip grants drifted from approved baseline';
    END IF;

    IF has_table_privilege('line_stock_reader','public.daily_chip_scores','SELECT')
       OR EXISTS (
         SELECT 1 FROM information_schema.columns
         WHERE table_schema='public' AND table_name='daily_chip_scores'
           AND column_name <> ALL(expected)
           AND has_column_privilege('line_stock_reader',
             'public.daily_chip_scores',column_name,'SELECT')
       )
       OR has_any_column_privilege(
         'line_stock_reader','public.line_messages','SELECT')
       OR has_any_column_privilege(
         'line_stock_reader','public.line_messages','INSERT')
       OR has_any_column_privilege(
         'line_stock_reader','public.daily_chip_scores','INSERT')
       OR has_any_column_privilege(
         'line_stock_reader','public.daily_chip_scores','UPDATE')
       OR has_table_privilege('line_stock_reader','public.daily_chip_scores','DELETE')
       OR has_table_privilege('line_stock_reader','public.daily_chip_scores','TRUNCATE')
    THEN
      RAISE EXCEPTION 'Reader privilege baseline is too broad; refusing grant';
    END IF;
END
$guard$;

-- Only the seven researched, non-personal fields needed by the optional
-- standalone LINE stock chip query. Never grant table-wide SELECT.
GRANT SELECT (
  market, stock_id, as_of_date, total_score, coverage_weight,
  institutional_score, margin_score
) ON TABLE public.daily_chip_scores TO line_stock_reader;

DO $verify$
DECLARE
    expected text[] := ARRAY[
      'as_of_date','coverage_weight','institutional_score','margin_score',
      'market','stock_id','total_score'
    ];
    missing_count integer;
BEGIN
    SELECT count(*) INTO missing_count FROM unnest(expected) AS col(name)
    WHERE NOT has_column_privilege(
      'line_stock_reader','public.daily_chip_scores',col.name,'SELECT'
    );
    IF missing_count <> 0
       OR has_table_privilege('line_stock_reader','public.daily_chip_scores','SELECT')
       OR EXISTS (
         SELECT 1 FROM information_schema.columns
         WHERE table_schema='public' AND table_name='daily_chip_scores'
           AND column_name <> ALL(expected)
           AND has_column_privilege('line_stock_reader',
             'public.daily_chip_scores',column_name,'SELECT')
       )
       OR has_any_column_privilege('line_stock_reader','public.line_messages','SELECT')
       OR has_any_column_privilege('line_stock_reader','public.daily_chip_scores','UPDATE')
       OR has_any_column_privilege('line_stock_reader','public.daily_chip_scores','INSERT')
    THEN
      RAISE EXCEPTION 'Grant verification failed; rolling back';
    END IF;
END
$verify$;
COMMIT;
