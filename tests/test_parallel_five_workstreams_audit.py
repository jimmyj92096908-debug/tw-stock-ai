"""No-network regression contracts for the five parallel workstreams."""
import unittest

from scripts.parallel_five_workstreams_audit import (
    CAPACITY_SQL, QUALITY_SQL, FACTOR_SQL, ACTION_SQL, HOLDOUT_SQL,
    STOP_BYTES, RESERVE_BYTES, evaluate,
)
from src.batch_indicator_catchup import CANDIDATES_SQL, CANDIDATES_240_ACTIVE_SQL
from src.calculate_smc import calculate_stock as calculate_smc_stock
from src.trained_factor_model import TRAINING_SQL, LATEST_MODEL_SQL, research_rank
from src.research_dataset import _identity


def fixtures():
    return dict(
        capacity=dict(database_bytes=610000000,raw_rows=1456000,
                      factor_rows=270000,raw_physical_bytes=400000000,
                      factor_physical_bytes=80000000),
        quality=[
            dict(market="twse",invalid_ohlcv=0,missing_open_close=115),
            dict(market="tpex",invalid_ohlcv=0,missing_open_close=260)],
        factors=[
            dict(market="twse",valid_raw_rows=487000,
                 missing_technical_keys=315000),
            dict(market="tpex",valid_raw_rows=968000,
                 missing_technical_keys=867000)],
        actions=dict(observed_actions=24,verified_actions=22,
                     unverified_actions=2,invalid_factors=0),
        holdout=dict(frozen_cohorts=1,completed_backtest_runs=0,
                     latest_signal="2026-11-20",latest_price="2026-11-20"),
    )


class ParallelAuditTests(unittest.TestCase):
    def test_five_workstreams_report_is_conservative_and_read_only(self):
        result=evaluate(**fixtures())
        self.assertFalse(result["fully_accepted"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["production_repair_performed"])
        self.assertEqual(len(result["five_workstreams"]),5)
        self.assertFalse(result["five_workstreams"]["free_capacity"][
            "existing_factor_debt_fits_with_reserve_ESTIMATE"])
        self.assertFalse(result["five_workstreams"]["holdout_integrity"][
            "independent_forward_performance_verified"])
        self.assertFalse(result["five_workstreams"]["corporate_actions"][
            "five_year_vintage_verified"])

    def test_capacity_pressure_and_invalid_denominators_fail_closed(self):
        x=fixtures()
        x["capacity"]["database_bytes"]=STOP_BYTES
        self.assertTrue(evaluate(**x)["five_workstreams"]["free_capacity"]["warning"])
        x=fixtures()
        x["factors"][0]["missing_technical_keys"]=9999999
        with self.assertRaises(ValueError):
            evaluate(**x)
        self.assertGreater(RESERVE_BYTES,0)

    def test_readonly_sql_all_data_tracks(self):
        for sql in (CAPACITY_SQL,QUALITY_SQL,FACTOR_SQL,ACTION_SQL,HOLDOUT_SQL):
            with self.subTest(sql=sql[:35]):
                self.assertIn("SELECT",sql)
                self.assertNotIn("DELETE FROM",sql.upper())
                self.assertNotIn("UPDATE PUBLIC.",sql.upper())
                self.assertNotIn("INSERT INTO",sql.upper())
        self.assertIn("public.model_stock_exclusions",QUALITY_SQL)
        self.assertIn("public.model_stock_exclusions",FACTOR_SQL)

    def test_exclusion_coverage_in_incremental_and_training_paths(self):
        import inspect
        from src import calculate_smc
        self.assertIn("public.model_stock_exclusions",CANDIDATES_SQL)
        self.assertIn("official_current_listed",CANDIDATES_240_ACTIVE_SQL)
        self.assertIn("public.model_stock_exclusions",TRAINING_SQL)
        self.assertIn("public.model_stock_exclusions",LATEST_MODEL_SQL)
        self.assertIn("public.model_stock_exclusions",inspect.getsource(calculate_smc))
        with self.assertRaisesRegex(ValueError,"excluded"):
            _identity(dict(market="twse",stock_id="1589"))


if __name__=="__main__":
    unittest.main()
