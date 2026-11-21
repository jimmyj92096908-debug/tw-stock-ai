"""Storage/capacity and derived-row debt must stay strictly read-only."""
from unittest import TestCase
from pathlib import Path
from unittest.mock import MagicMock,patch

from scripts import tpex_five_year_capacity_plan as m

ROOT=Path(__file__).resolve().parents[1]

def tables():
    return {
       "daily_prices":{"rows":400_000,"bytes":96_000_000},
       "daily_adjusted_prices":{"rows":275_000,"bytes":70_000_000},
       "daily_technicals":{"rows":275_000,"bytes":58_000_000},
       "daily_smc":{"rows":275_000,"bytes":52_000_000}
    }

def cohort(n=6,price=250,missing=100):
    return [
      {"stock_id":str(1100+i),"price_rows":price,
       "missing_adjusted":missing,"missing_technical":missing,
       "missing_smc":missing,"valid_days":price,"latest_valid":None}
      for i in range(n)
    ]

class TPExCapacityPlannerTests(TestCase):
    def test_capacity_projections_are_conservative_and_strict(self):
        result=m.formulate_plan(340_000_000,tables(),
            {"known_anchor_days":1212,"full_market_source_days":250,
             "incomplete_anchor_days":962},cohort())
        self.assertEqual(result["source"]["incomplete_anchor_days"],962)
        self.assertEqual(result["database_bytes"],340_000_000)
        self.assertEqual(result["headroom_to_internal_safety_stop_bytes"],460_000_000)
        self.assertEqual(len(result["selected_preview_stocks"]),5)
        self.assertEqual(result["selected_preview_raw_price_rows"],1250)
        self.assertTrue(result["bounded_preview_passes_free_storage_check"])
        self.assertFalse(result["manual_derived_recompute_permitted_now"])
        self.assertTrue(result["must_wait_until_source_campaign_stopped"])
        self.assertFalse(result["full_five_year_per_stock_history_verified"])
        self.assertFalse(result["derived_rows_modified"])
        self.assertFalse(result["LINE_or_trading_enabled"])
        self.assertGreater(result["source_plus_full_derived_projection_bytes"],
                           result["estimated_database_after_full_derived"])
        self.assertGreater(result["conservative_bytes_per_new_row"]["daily_prices"],240)

    def test_exceeding_safety_stop_refuses_new_derived_batches(self):
        value=m.formulate_plan(799_000_000,tables(),
            {"known_anchor_days":1212,"full_market_source_days":1100,
             "incomplete_anchor_days":112},cohort(3,400,300))
        self.assertFalse(value["bounded_preview_passes_free_storage_check"])
        self.assertFalse(value["full_history_derivatives_fit_free_safety_budget_estimate"])
        self.assertFalse(value["manual_derived_recompute_permitted_now"])

    def test_report_rejects_wrong_or_duplicate_cohort_and_impossible_counts(self):
        days={"known_anchor_days":1212,"full_market_source_days":250,
              "incomplete_anchor_days":962}
        for bad in (
            [],
            [cohort(1)[0]]*2,
            [{**cohort(1)[0],"missing_adjusted":260}],
            [{**cohort(1)[0],"missing_smc":-1}],
            [{**cohort(1)[0],"price_rows":True}],
        ):
            with self.assertRaises(ValueError):
                m.formulate_plan(300_000_000,tables(),days,bad)
        with self.assertRaises(ValueError):
            m.formulate_plan(300_000_000,tables(),{
                **days,"incomplete_anchor_days":961},cohort(1))
        with self.assertRaises(ValueError):
            m.formulate_plan(300_000_000,tables(),{
                **days,"full_market_source_days":True},cohort(1))
        with self.assertRaises(ValueError):
            m.formulate_plan(300_000_000,{
               **tables(),"daily_smc":{"rows":0,"bytes":0}
            },days,cohort(1))

    def test_missing_derived_uses_count_star_not_count_nullable_join_key(self):
        sql=m.MISSING_SQL.upper()
        for alias in ("A","T","S"):
            self.assertIn("COUNT(*) FILTER (WHERE "+alias+".TRADE_DATE IS NULL)",sql)
            self.assertNotIn("COUNT("+alias+".TRADE_DATE) FILTER (WHERE "
                             +alias+".TRADE_DATE IS NULL)",sql)
        self.assertIn("WHERE P.MARKET='TPEX'",sql)
        self.assertNotIn("UPDATE ",m.MISSING_SQL.upper())
        self.assertNotIn("DELETE ",m.MISSING_SQL.upper())

    def test_inspect_runs_in_neon_readonly_repeatable_read(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def run_sql(sql,*args):
            result=MagicMock()
            if sql==m.DB_SIZE_SQL:
                result.fetchone.return_value={"size_bytes":330_000_000}
            elif sql==m.TABLE_SQL:
                result.fetchall.return_value=[
                    {"tbl":key,**val} for key,val in tables().items()]
            elif sql==m.SOURCE_DAYS_SQL:
                result.fetchone.return_value={
                    "known_anchor_days":1212,"full_market_source_days":250,
                    "incomplete_anchor_days":962
                }
            elif sql==m.MISSING_SQL:
                result.fetchall.return_value=[dict(x) for x in cohort(1)]
            return result
        conn.execute.side_effect=run_sql
        with patch.object(m.psycopg,"connect",return_value=conn) as connect:
            value=m.inspect("existing-secret-url")
        self.assertEqual(value["scope"],
                         "TPEX_FIVE_YEAR_CAPACITY_AND_DERIVED_RECALC_READ_ONLY_PLAN")
        self.assertFalse(value["manual_derived_recompute_permitted_now"])
        self.assertIn("default_transaction_read_only=on",
                      connect.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ READ ONLY",
                      conn.execute.call_args_list[0].args[0])

    def test_workflow_read_only_job_and_safe_manual_reentry(self):
        wf=(ROOT/".github/workflows/tpex-five-year-capacity-postflight.yml").read_text()
        self.assertIn("TPEx Five-Year Dated Market Full Free Campaign",wf)
        self.assertIn("  workflow_dispatch:",wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("STOCK_TPEX_FIVE_YEAR_SOURCE_WRITE_ENABLED",wf)
        self.assertNotIn("--apply",wf)
        self.assertIn("tpex_five_year_capacity_plan.py",wf)
        recovery=(ROOT/".github/workflows/tpex-five-year-market-full.yml").read_text()
        self.assertIn("  workflow_dispatch:",recovery)
        self.assertIn("default: false",recovery)
        self.assertIn("inputs.apply == true",recovery)
        self.assertIn("twstock-tpex-dated-official-history",recovery)
        self.assertNotIn("  schedule:",recovery)
        # Source verification stays required even for manual resume.
        self.assertIn("python -m unittest tests.test_tpex_five_year_market_backfill",recovery)
        self.assertIn("github.event_name == 'workflow_run'",recovery)
        acceptance=(ROOT/".github/workflows/tpex-five-year-source-acceptance.yml").read_text()
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'",acceptance)
