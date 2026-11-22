"""Synthetic tests: historical official ex-reference parity never releases model."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.twse_2022_dividend_exref_readonly import (
    EVENTS, SCOPE, verify_precise_cash_reference,
)
from scripts.twse_2022_known_dividend_gap_offline import (
    classify_historical_dividend_gaps,
)
from tests.test_twse_2022_known_dividend_gap_offline import prior
from tests.test_twse_2021_22_traded_240_warmup_readonly import input_fixture


def fixture():
    original, days, _, _ = input_fixture()
    gaps = classify_historical_dividend_gaps(prior())
    witnessed = {
        ("2327", date(2022, 7, 1)): Decimal("282"),
        ("2327", date(2022, 7, 4)): Decimal("281"),
        ("2603", date(2022, 6, 28)): Decimal("108.5"),
        ("2603", date(2022, 6, 29)): Decimal("90.6"),
    }
    return original, dict(original), gaps, set(days), witnessed


def check(fix):
    return verify_precise_cash_reference(*fix)


class ExactDividendDateReferenceTests(unittest.TestCase):
    def test_both_historical_cash_issuer_announcements_and_price_refs(self):
        r = check(fixture())
        self.assertEqual(r["scope"], SCOPE)
        self.assertEqual(r["dated_two_dividend_event_reference_parity_count"], 2)
        self.assertEqual([x["stock_id"]
                          for x in r["dated_two_dividend_event_research_witnesses"]],
                         ["2327", "2603"])
        self.assertEqual(r["source_2022_verified_observed_market_days"], 246)
        self.assertEqual(r["production_neon_writes"], 0)
        self.assertEqual(r["line_messages_sent"], 0)
        self.assertEqual(r["live_model_release_decision"], "BLOCKED")
        self.assertFalse(r["full_historical_company_action_universe_proven"])
        self.assertFalse(r["fully_adjusted_sma240_or_total_return_label_approved"])
        self.assertFalse(r["source_bars_or_prices_rewritten"])
        for entry in r["dated_two_dividend_event_research_witnesses"]:
            self.assertTrue(entry["ex_reference_formula_parity_within_0_01_ntd"])
            self.assertTrue(entry["actual_authenticated_source_pre_ex_close_matches_evidence"])
            self.assertFalse(entry["cash_available_on_ex_dividend_day"])
            self.assertFalse(entry["confirmed_verified_cash_dividend_event_inserted_to_neon"])
            self.assertFalse(entry["total_return_or_adjusted_sma240_recomputed"])

    def test_authoritative_2022_cash_precision_and_reference_tolerance(self):
        self.assertEqual(
            EVENTS["2327"]["declared_cash_per_old_share"], Decimal("10.10281345"))
        self.assertEqual(
            EVENTS["2603"]["declared_cash_per_old_share"], Decimal("17.99999637"))
        self.assertLess(abs(
            Decimal("282") - Decimal("10.10281345") - Decimal("271.89")),
            Decimal(".01"))
        self.assertLess(abs(
            Decimal("108.5") - Decimal("17.99999637") - Decimal("90.50")),
            Decimal(".01"))

    def test_wrong_historical_close_fails_closed(self):
        data = list(fixture())
        data[4][("2327", date(2022, 7, 1))] = Decimal("283")
        with self.assertRaisesRegex(ValueError, "Real pre-ex stock close"):
            check(data)
        data = list(fixture())
        data[4][("2603", date(2022, 6, 28))] = Decimal("108")
        with self.assertRaises(ValueError):
            check(data)

    def test_fake_missing_or_extra_ex_bar_fails_closed(self):
        data = list(fixture())
        del data[4][("2327", date(2022, 7, 4))]
        with self.assertRaisesRegex(ValueError, "Missing/phantom"):
            check(data)
        data = list(fixture())
        data[4][("2327", date(2022, 7, 5))] = Decimal("280")
        with self.assertRaises(ValueError):
            check(data)

    def test_known_absent_cash_event_must_match_prior_report(self):
        data = list(fixture())
        data[2]["events_confirmed_missing_from_prior_neon_cash_dividend_inventory"] = 1
        with self.assertRaisesRegex(ValueError, "gap evidence"):
            check(data)
        data = list(fixture())
        data[2]["per_stock_known_dividend_event_gaps"][0][
            "dated_event_vs_prior_neon_status"] = "PRESENT"
        with self.assertRaisesRegex(ValueError, "Unverified previously missing"):
            check(data)

    def test_unverified_release_neon_write_or_aes_drift_fails_closed(self):
        data = list(fixture())
        data[1]["neon_write_operations"] = 1
        with self.assertRaisesRegex(ValueError, "drifted"):
            check(data)
        data = list(fixture())
        data[1]["private_result_fingerprint_sha256"] = "source-drift"
        with self.assertRaisesRegex(ValueError, "drifted"):
            check(data)
        data = list(fixture())
        data[2]["live_model_release_decision"] = "APPROVED"
        with self.assertRaises(ValueError):
            check(data)

    def test_dividend_notice_after_or_on_ex_date_cannot_be_pit_used(self):
        fix = fixture()
        changed = dict(EVENTS["2327"], issuer_announcement_date=date(2022, 7, 5))
        with patch.dict(EVENTS, {"2327": changed}):
            with self.assertRaisesRegex(ValueError, "As-of"):
                check(fix)

    def test_rounding_not_false_exact_amount_and_conflict_detected(self):
        fix = fixture()
        changed = dict(EVENTS["2327"], declared_cash_per_old_share=Decimal("10"))
        with patch.dict(EVENTS, {"2327": changed}):
            with self.assertRaisesRegex(ValueError, "reference mismatch"):
                check(fix)

    def test_non_decimal_or_invalid_share_close_rejected(self):
        data = list(fixture())
        data[4][("2603", date(2022, 6, 29))] = 90.6
        with self.assertRaisesRegex(ValueError, "Real pre-ex"):
            check(data)
        data = list(fixture())
        data[4][("2603", date(2022, 6, 29))] = Decimal("NaN")
        with self.assertRaises(ValueError):
            check(data)

    def test_help_does_not_require_secret_or_server(self):
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.pop("STOCK_ARCHIVE_KEY_HEX", None)
        env.pop("PYTHONPATH", None)
        run = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2022_dividend_exref_readonly", "--help"],
            cwd=root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--gap-report", run.stdout)
        self.assertIn("--archive-2022", run.stdout)


if __name__ == "__main__":
    unittest.main()
