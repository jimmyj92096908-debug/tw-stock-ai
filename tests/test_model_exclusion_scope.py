"""Offline exclusion-scope regression checks: no LINE, network or database writes."""
import unittest

from src.twse_dated_history import ACTIVE_ALLOWED_SQL
from scripts.twse_five_year_maturity_audit import MATURITY_SQL
from src.factor_model_validation import EVALUATION_SQL
from src.factor_model_v2 import ADJUSTED_EVALUATION_SQL
from src.composite_score import SCORABLE_STOCKS_SQL, LATEST_VALID_TECH_SQL
from src import calculate_technicals, build_adjusted_prices


class ModelExclusionScopeTests(unittest.TestCase):
    def test_history_import_maturity_and_validation_obey_exclusions(self):
        for sql in (ACTIVE_ALLOWED_SQL, MATURITY_SQL, EVALUATION_SQL,
                    ADJUSTED_EVALUATION_SQL, SCORABLE_STOCKS_SQL,
                    LATEST_VALID_TECH_SQL):
            with self.subTest(sql=sql[:90]):
                self.assertIn("public.model_stock_exclusions", sql)
                self.assertIn("NOT EXISTS", sql)
                self.assertIn("x.market=", sql)
                self.assertIn("x.stock_id=", sql)

    def test_history_scope_is_still_official_and_no_price_overwrite(self):
        self.assertIn("official_current_listed", ACTIVE_ALLOWED_SQL)
        self.assertIn("official_current_listed", MATURITY_SQL)
        self.assertIn("LEFT JOIN public.daily_prices", MATURITY_SQL)
        self.assertNotIn("ON CONFLICT DO UPDATE", ACTIVE_ALLOWED_SQL.upper())

    def test_derived_pipeline_enforces_registry_in_every_source_select(self):
        import inspect
        tech=inspect.getsource(calculate_technicals)
        adjusted=inspect.getsource(build_adjusted_prices)
        self.assertGreaterEqual(tech.count('public.model_stock_exclusions'),3)
        self.assertGreaterEqual(adjusted.count('public.model_stock_exclusions'),2)
        self.assertIn('NOT EXISTS', tech)
        self.assertIn('NOT EXISTS', adjusted)

    def test_validation_stays_point_in_time_and_read_only(self):
        self.assertIn("LEAD(close,1)", EVALUATION_SQL)
        self.assertIn("LEAD(close,6)", EVALUATION_SQL)
        self.assertNotIn("UPDATE public.daily_prices", EVALUATION_SQL)
        self.assertNotIn("DELETE FROM", EVALUATION_SQL.upper())


if __name__ == "__main__":
    unittest.main()
