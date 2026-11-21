"""Safety regression tests for one-time TPEx 60-session research coverage."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts import tpex_after_history_catchup as task


def snap(eligible=120, indicators=100, matched=90, *, source_days=60,
         raw_price_rows=250_000, database_bytes=260_000_000):
    return {
        "eligible": eligible, "indicators": indicators,
        "matched": matched, "source_days": source_days,
        "raw_price_rows": raw_price_rows,
        "database_bytes": database_bytes,
    }


GATES = {
    "STOCK_TPEX_INDICATOR_CAMPAIGN_WRITE_ENABLED": "yes",
    "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED": "yes",
}


class TPExAfterHistoryCatchupTests(unittest.TestCase):
    def test_default_preview_cannot_calculate_or_score(self):
        with (
            patch.object(task, "capture", return_value=snap()),
            patch.object(task, "indicator_run") as ind,
            patch.object(task, "calculate_all") as calc,
        ):
            report = task.execute("fake", apply=False, report_path=None)
        self.assertFalse(report["completed"])
        self.assertFalse(report["raw_prices_modified"])
        ind.assert_not_called()
        calc.assert_not_called()

    def test_explicit_gates_and_round_limits(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "write gates"):
                task.execute("fake", apply=True)
        for rounds in (-1, 46, 100):
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                task.execute("fake", max_rounds=rounds)
        with self.assertRaisesRegex(ValueError, "write gates"):
            task.execute("fake", apply=True, max_rounds=0)

    def test_successful_tpex_only_indicators_then_missing_only_scores(self):
        cohort1 = [("tpex", str(i)) for i in range(1000, 1010)]
        cohort2 = [("tpex", str(i)) for i in range(1010, 1020)]
        cohort3 = [("tpex", str(i)) for i in range(1020, 1030)]
        sequence = [
            snap(), snap(indicators=120),
            snap(indicators=120, matched=100),
            snap(indicators=120, matched=110),
            snap(indicators=120, matched=120),
        ]
        with (
            patch.dict(os.environ, GATES),
            patch.object(task, "capture", side_effect=sequence),
            patch.object(task, "indicator_run",
                         return_value=[{"status": "verified"}] * 20) as ind,
            patch.object(task, "missing_scores",
                         side_effect=[cohort1, cohort2, cohort3, []]) as missing,
            patch.object(task, "calculate_all", return_value=10) as calc,
        ):
            result = task.execute("fake", apply=True, max_rounds=4)
        self.assertTrue(result["completed"])
        self.assertEqual(len(result["rounds"]), 1)
        self.assertEqual(len(result["score_batches"]), 3)
        ind.assert_called_once_with("fake", apply=True, per_market=20, markets=("tpex",))
        self.assertEqual(calc.call_count, 3)
        calc.assert_any_call("fake", stocks=cohort1, missing_only=True)
        self.assertEqual(missing.call_count, 4)
        self.assertFalse(result["line_messages_sent"])
        self.assertFalse(result["trading_enabled"])

    def test_insufficient_source_history_never_starts_writing(self):
        with (
            patch.dict(os.environ, GATES),
            patch.object(task, "capture", return_value=snap(source_days=12)),
            patch.object(task, "indicator_run") as ind,
        ):
            with self.assertRaisesRegex(RuntimeError, "Insufficient"):
                task.execute("fake", apply=True, max_rounds=1)
            ind.assert_not_called()

    def test_failed_indicator_and_raw_price_change_stop_scoring(self):
        for changed, phrase in (
            (snap(indicators=120, raw_price_rows=250_001), "Raw market history"),
            (snap(indicators=100), "no progress"),
        ):
            with (
                self.subTest(phrase=phrase),
                patch.dict(os.environ, GATES),
                patch.object(task, "capture", side_effect=[snap(), changed]),
                patch.object(task, "indicator_run",
                             return_value=[{"status": "verified"}]),
                patch.object(task, "calculate_all") as calc,
            ):
                with self.assertRaisesRegex(RuntimeError, phrase):
                    task.execute("fake", apply=True, max_rounds=1)
                calc.assert_not_called()

    def test_missing_score_batch_cannot_mask_unscorable_records(self):
        cohort = [("tpex", str(i)) for i in range(1000, 1010)]
        with (
            patch.dict(os.environ, GATES),
            patch.object(task, "capture",
                         side_effect=[snap(indicators=120), snap(indicators=120)]),
            patch.object(task, "missing_scores", return_value=cohort),
            patch.object(task, "calculate_all", return_value=0),
        ):
            with self.assertRaisesRegex(RuntimeError, "made no progress"):
                task.execute("fake", apply=True, max_rounds=1)

    def test_no_raw_write_sql_and_storage_hard_stop(self):
        self.assertNotIn("INSERT INTO public.daily_prices", task.STATE_SQL.upper())
        self.assertNotIn("UPDATE public.daily_prices", task.STATE_SQL.upper())
        self.assertIn("source='TPEX_DATED_OTC_EW'", task.STATE_SQL)
        self.assertIn("NOT EXISTS", task.MISSING_SCORE_SQL)
        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def execute(self, *_):
                return self
            def fetchone(self):
                return snap(database_bytes=801_000_000)
        with patch.object(task.psycopg, "connect", return_value=FakeConnection()):
            with self.assertRaisesRegex(RuntimeError, "free database"):
                task.capture("postgresql://disposable")


if __name__ == "__main__":
    unittest.main()
