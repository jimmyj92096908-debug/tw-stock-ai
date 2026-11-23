"""Synthetic previous receipts: 2022 162 AES + 84 Neon vs full 5-year stock maturity."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2022_aes_neon_five_year_overlay_offline import (
    SCOPE, reconcile_offline,
)
from scripts.twse_tpex_five_year_neon_only_cohort_readonly import (
    SCOPE as NEON_SCOPE,
)
from scripts.twse_2022_aes_neon_readonly_240_panel import (
    FROZEN_STOCKS,
)


def old():
    return {
        "schema_version": 1,
        "scope": "TWSE_2022_LOCAL_AES_EXISTING_NEON_READONLY_FROZEN20_FACTOR_RESEARCH",
        "neon_transaction_mode": "READ_ONLY",
        "neon_write_operations": 0,
        "line_messages_sent": 0,
        "live_model_release_decision": "BLOCKED",
        "complete_five_year_history_verified": False,
        "dividends_splits_or_total_return_adjusted": False,
        "historical_delisted_survivorship_bias_removed": False,
        "frozen_current_research_stock_count": len(FROZEN_STOCKS),
        "frozen_stocks_with_complete_last_240_source_sessions": 18,
        "missing_sma240_stock_count": 2,
        "local_2022_source_sessions": 162,
        "neon_source_sessions": 84,
        "overlapping_source_sessions": 0,
        "unique_observed_2022_source_sessions": 246,
        "first_combined_session": "2022-01-03",
        "last_combined_session": "2022-12-30",
    }


def annual(market, year, any_days, high_days, rows, n):
    return {
        "year": year,
        "days_with_any_neon_eligible_source_bars": any_days,
        "days_with_at_least_500_eligible_source_bars": high_days,
        "neon_stored_valid_source_stock_bars": rows,
    }


def fresh():
    yearly = {
        "twse": [
            annual("twse", 2021, 28, 0, 552, 1092),
            annual("twse", 2022, 246, 84, 83294, 1092),
            annual("twse", 2023, 239, 239, 231655, 1092),
            annual("twse", 2024, 242, 242, 243484, 1092),
            annual("twse", 2025, 243, 243, 252421, 1092),
            annual("twse", 2026, 213, 213, 229215, 1092),
        ],
        "tpex": [
            annual("tpex", 2021, 28, 28, 20585, 898),
            annual("tpex", 2022, 246, 246, 183123, 898),
            annual("tpex", 2023, 239, 239, 184133, 898),
            annual("tpex", 2024, 242, 242, 193140, 898),
            annual("tpex", 2025, 243, 243, 200369, 898),
            annual("tpex", 2026, 213, 213, 184147, 898),
        ],
    }
    return {
        "schema_version": 1, "scope": NEON_SCOPE,
        "model_release": "BLOCKED",
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "five_year_history_completed": False,
        "excludes_owner_private_aes_and_non_neon_source_history": True,
        "current_listed_issuers_only_not_historical_pit_membership": True,
        "owner_aes_2021_2022_source_not_included": True,
        "window_start_inclusive": "2021-11-23",
        "window_end_exclusive": "2026-11-23",
        "market": {
            "twse": {
                "official_current_listed_stocks_excluding_1589": 1092,
                "with_at_least_240_valid_stored_days": 1057,
                "with_at_least_1000_valid_stored_days": 936,
                "yearly_neon_source_observations": yearly["twse"],
            },
            "tpex": {
                "official_current_listed_stocks_excluding_1589": 898,
                "with_at_least_240_valid_stored_days": 851,
                "with_at_least_1000_valid_stored_days": 750,
                "yearly_neon_source_observations": yearly["tpex"],
            },
        },
    }


class Owned2022AesNeonOverlayTests(unittest.TestCase):
    def test_genuine_owner_reconciled_five_year_snapshot_still_blocks(self):
        x = reconcile_offline(old(), fresh())
        self.assertEqual(x["scope"], SCOPE)
        self.assertEqual(x["twse_2022_authenticated_local_aes_source_days"], 162)
        self.assertEqual(x["twse_2022_verified_neon_official_bulk_source_days"], 84)
        self.assertEqual(x["twse_2022_deduplicated_observed_source_calendar_dates"], 246)
        self.assertEqual(x["twse_2022_prior_source_calendar_date_overlap"], 0)
        self.assertEqual(x["current_listed_stocks_total"], 1990)
        self.assertEqual(x["neon_only_current_listed_240_day_ready_total"], 1908)
        self.assertEqual(x["neon_only_current_listed_1000_day_ready_total"], 1686)
        self.assertEqual(x["twse_current_frozen20_raw_sma240_by_market_day_complete"], 18)
        self.assertEqual(x["twse_current_frozen20_nontrade_halt_stock_days_known"], 14)
        self.assertFalse(x["2022_neon_500_bar_dates_and_source_bulk_84_day_sets_proven_identical"])
        self.assertFalse(x["2022_private_aes_has_at_least_500_today_listed_stocks_on_all_162_dates_proven"])
        self.assertFalse(x["virtual_2022_twse_full_market_per_stock_coverage_verified"])
        self.assertTrue(x["owner_private_aes_not_counted_as_existing_neon_rows"])
        self.assertFalse(x["complete_five_year_price_bars_verified"])
        self.assertFalse(x["complete_adjusted_dividends_and_total_return_proven"])
        self.assertFalse(x["history_survivorship_unbiased"])
        self.assertEqual(x["production_neon_writes"], 0)
        self.assertEqual(x["line_messages_sent"], 0)
        self.assertEqual(x["model_release"], "BLOCKED")
        self.assertNotIn("actual_adjusted_sma", str(x))

    def test_2022_overlap_or_reinterpreted_84_full_days_never_pass(self):
        before = old()
        before["overlapping_source_sessions"] = 1
        with self.assertRaises(ValueError):
            reconcile_offline(before, fresh())
        before = old()
        before["local_2022_source_sessions"] = 163
        with self.assertRaises(ValueError):
            reconcile_offline(before, fresh())
        baseline = fresh()
        baseline["market"]["twse"]["yearly_neon_source_observations"][1][
            "days_with_at_least_500_eligible_source_bars"] = 83
        with self.assertRaises(ValueError):
            reconcile_offline(old(), baseline)
        baseline = fresh()
        baseline["market"]["tpex"]["yearly_neon_source_observations"][1][
            "days_with_at_least_500_eligible_source_bars"] = 245
        with self.assertRaises(ValueError):
            reconcile_offline(old(), baseline)

    def test_changed_current_listed_roster_or_secret_writes_rejected(self):
        bad = old();bad["neon_write_operations"] = 1
        with self.assertRaises(ValueError):
            reconcile_offline(bad, fresh())
        bad = fresh();bad["production_neon_writes"] = 1
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)
        bad = fresh();bad["owner_aes_2021_2022_source_not_included"] = False
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)
        bad = fresh();bad["market"]["twse"][
            "official_current_listed_stocks_excluding_1589"] = 100
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)

    def test_yearly_missing_2022_or_duplicate_year_fails(self):
        bad = fresh()
        bad["market"]["twse"]["yearly_neon_source_observations"] = [
            x for x in bad["market"]["twse"]["yearly_neon_source_observations"]
            if x["year"] != 2022
        ]
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)
        bad = fresh()
        bad["market"]["tpex"]["yearly_neon_source_observations"][4]["year"] = 2024
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)

    def test_outside_owner_five_year_window_fails(self):
        bad = fresh();bad["window_start_inclusive"] = "2023-01-01"
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)
        bad = fresh();bad["window_end_exclusive"] = "2022-12-30"
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)

    def test_unreleased_2022_corporate_action_or_leaky_report_refused(self):
        before = old()
        before["dividends_splits_or_total_return_adjusted"] = True
        with self.assertRaises(ValueError):
            reconcile_offline(before, fresh())
        bad = fresh()
        bad["model_release"] = "APPROVED"
        with self.assertRaises(ValueError):
            reconcile_offline(old(), bad)

    def test_cli_help_without_credential_or_private_owner_files(self):
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        for key in ("DATABASE_URL", "STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(key, None)
        process = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2022_aes_neon_five_year_overlay_offline",
             "--help"],
            cwd=root,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("--prior-2022-panel",process.stdout)
        self.assertIn("--neon-five-year-report",process.stdout)


if __name__ == "__main__":
    unittest.main()
