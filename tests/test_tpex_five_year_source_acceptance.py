"""Read-only and honest five-year TPEx official source acceptance tests."""
from datetime import date
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from scripts import tpex_five_year_source_acceptance as m

ROOT=Path(__file__).resolve().parents[1]

def row(day, valid, dated=0, openapi=0):
    return {"trade_date":day, "valid_rows":valid,
            "official_dated_rows":dated,"official_openapi_rows":openapi}

class TPExFiveYearSourceAcceptanceTests(TestCase):
    def test_full_market_source_coverage_independent_of_short_stock_history(self):
        observed=[
            row(date(2022,12,30),755,dated=755),
            row(date(2025,12,31),852,dated=852),
            row(date(2026,11,20),880,openapi=880)
        ]
        x=m.classify(observed)
        self.assertEqual(x["independent_anchored_dates"],3)
        self.assertEqual(x["verified_official_full_market_dates"],3)
        self.assertEqual(x["source_market_date_coverage_percent"],100)
        self.assertEqual(x["unverified_anchored_dates"],0)

    def test_missing_market_source_date_is_never_inferred_from_few_stock_rows(self):
        observed=[row(date(2021,11,22),16),row(date(2025,12,31),18,dated=852)]
        report=m.classify(observed)
        self.assertEqual(report["independent_anchored_dates"],2)
        self.assertEqual(report["verified_official_full_market_dates"],1)
        self.assertEqual(report["unverified_anchored_dates"],1)
        self.assertIn("2021-11-22",report["recent_missing_date_examples"])
        self.assertEqual(report["source_market_date_coverage_percent"],50)
        for invalid in ([],[observed[0],observed[0]]):
            with self.assertRaises(ValueError):
                m.classify(invalid)

    def test_stock_specific_five_year_completion_is_not_claimed(self):
        import inspect
        source=inspect.getsource(m)
        self.assertIn('"full_five_year_stock_by_stock_listing_history_verified":False',source)
        self.assertIn('historical_factors_fresh',source)
        self.assertIn('default_transaction_read_only=on',source)
        self.assertIn('REPEATABLE READ READ ONLY',source)
        self.assertNotIn('UPDATE public.daily_prices',source)
        self.assertNotIn('INSERT INTO public.daily_prices',source)
        self.assertNotIn('DELETE FROM public.daily_prices',source)
        self.assertEqual(m.MIN_FULL_MARKET_ROWS,500)
        self.assertEqual(m.MIN_ANCHORED_SESSIONS,1100)
        self.assertEqual(m.MAX_DB_BYTES,800_000_000)

    def test_one_hop_readonly_acceptance_is_not_independent_write(self):
        workflow=(ROOT/".github/workflows/tpex-five-year-source-acceptance.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_run:",workflow)
        self.assertIn('"TPEx Five-Year Dated Market Full Free Campaign"',workflow)
        self.assertIn('github.event.workflow_run.head_branch == \'main\'',workflow)
        self.assertIn('github.event.workflow_run.repository.full_name == github.repository',workflow)
        self.assertNotIn("  schedule:",workflow)
        self.assertNotIn("STOCK_TPEX_FIVE_YEAR_SOURCE_WRITE_ENABLED",workflow)
        self.assertNotIn("--apply",workflow)
        self.assertIn("tpex_five_year_source_acceptance.py",workflow)
