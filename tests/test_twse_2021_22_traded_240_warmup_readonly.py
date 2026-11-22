"""Synthetic-only test of owner AES 2021/22 stock-trading warmup evidence."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2021_22_traded_240_warmup_readonly import (
    EXPECTED_2021, EXPECTED_HALT_SESSIONS, STOCKS,
    summarize_real_traded_warmup,
)


def market_dates():
    days = []
    d = date(2022, 1, 3)
    while len(days) < 246:
        if d.weekday() < 5 and d != date(2022, 9, 9):
            days.append(d)
        d += timedelta(days=1)
    assert all(date.fromisoformat(x) in days
               for sid in STOCKS for x in EXPECTED_HALT_SESSIONS[sid])
    return days


def input_fixture():
    market = market_dates()
    old = {sid: set(EXPECTED_2021) for sid in STOCKS}
    new = {
        sid: set(market) - {date.fromisoformat(x)
                            for x in EXPECTED_HALT_SESSIONS[sid]}
        for sid in STOCKS
    }
    details = [{
        "stock_id": sid,
        "missing_observed_trade_dates": list(EXPECTED_HALT_SESSIONS[sid]),
        "missing_observed_trade_day_count": 7,
        "source_refetch_or_neon_write_authorized": False,
    } for sid in STOCKS]
    report = {
        "schema_version": 1,
        "scope": "TWSE_2022_LOCAL_AES_EXISTING_NEON_READONLY_FROZEN20_FACTOR_RESEARCH",
        "neon_transaction_mode": "READ_ONLY",
        "local_2022_source_sessions": 162,
        "neon_source_sessions": 84,
        "overlapping_source_sessions": 0,
        "unique_observed_2022_source_sessions": 246,
        "first_combined_session": min(market).isoformat(),
        "last_combined_session": max(market).isoformat(),
        "frozen_current_research_stock_count": 20,
        "frozen_stocks_with_complete_last_240_source_sessions": 18,
        "sma240_stock_day_gap_diagnostics_available": True,
        "missing_sma240_stock_count": 2,
        "missing_sma240_stock_day_details": details,
        "private_result_fingerprint_sha256": "0"*64,
        "neon_write_operations": 0,
        "line_messages_sent": 0,
        "complete_five_year_history_verified": False,
        "dividends_splits_or_total_return_adjusted": False,
        "live_model_release_decision": "BLOCKED",
    }
    return report, market, old, new


class Traded240WarmupOfflineTests(unittest.TestCase):
    def test_both_real_stock_trading_series_have_240_2021_2022_bars(self):
        report, market, old, new = input_fixture()
        result = summarize_real_traded_warmup(
            report, dict(report), market, EXPECTED_2021, old, new,
        )
        entries = result["stock_traded_day_research_warmup_proofs"]
        self.assertEqual([e["stock_id"] for e in entries], ["2327", "2603"])
        for e in entries:
            self.assertEqual(e["authenticated_2021_real_trading_days"], 28)
            self.assertEqual(e["authenticated_2022_real_trading_days"], 239)
            self.assertEqual(e["actual_source_bars_from_2021_and_2022"], 267)
            self.assertEqual(e["verified_2022_no_trade_cash_reduction_market_days"], 7)
            self.assertTrue(e["latest_240_real_stock_trading_dates_selectable"])
            self.assertEqual(e["last240_earliest_real_trading_date"], "2021-12-30")
            self.assertEqual(e["last240_latest_real_trading_date"], max(market).isoformat())
            self.assertFalse(e["underlying_price_adjusted_for_cash_reduction"])
            self.assertFalse(e["adjusted_sma240_or_factor_recomputed"])
        self.assertEqual(result["source_2022_market_session_sma240_eligible_unchanged"], 18)
        self.assertEqual(result["verified_halt_days_not_replaced_by_fake_bars"], 14)
        self.assertEqual(result["production_neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")
        self.assertFalse(result["cash_reduction_or_total_return_price_adjusted"])

    def test_missing_2021_real_bar_does_not_silently_pass(self):
        report, market, old, new = input_fixture()
        old["2603"].remove(max(EXPECTED_2021))
        with self.assertRaisesRegex(ValueError, "warmup"):
            summarize_real_traded_warmup(
                report, dict(report), market, EXPECTED_2021, old, new)

    def test_unknown_2022_missing_stock_day_never_counted_as_cash_reduction(self):
        report, market, old, new = input_fixture()
        unexpected = date(2022, 6, 1)
        self.assertNotIn(unexpected, {
            date.fromisoformat(x) for x in EXPECTED_HALT_SESSIONS["2327"]})
        new["2327"].remove(unexpected)
        with self.assertRaisesRegex(ValueError, "Unexpected 2022 stock-day"):
            summarize_real_traded_warmup(
                report, dict(report), market, EXPECTED_2021, old, new)

    def test_recomputed_neon_or_aes_evidence_change_refused(self):
        report, market, old, new = input_fixture()
        for key, value in (
            ("unique_observed_2022_source_sessions", 245),
            ("private_result_fingerprint_sha256", "different"),
            ("neon_write_operations", 1),
            ("live_model_release_decision", "APPROVED"),
        ):
            now = dict(report)
            now[key] = value
            with self.assertRaisesRegex(ValueError, "changed", msg=key):
                summarize_real_traded_warmup(
                    report, now, market, EXPECTED_2021, old, new)

    def test_any_2021_archive_session_not_verified_refused(self):
        report, market, old, new = input_fixture()
        dates = set(EXPECTED_2021)
        dates.remove(max(dates))
        with self.assertRaisesRegex(ValueError, "calendar mismatch"):
            summarize_real_traded_warmup(
                report, dict(report), market, dates, old, new)

    def test_exclusion_and_inconsistent_2022_gap_report_refused(self):
        report, market, old, new = input_fixture()
        report["missing_sma240_stock_day_details"][0]["stock_id"] = "1589"
        with self.assertRaises(ValueError):
            summarize_real_traded_warmup(
                report, dict(report), market, EXPECTED_2021, old, new)

    def test_help_has_no_credentials_or_database_requirement(self):
        repo = Path(__file__).resolve().parents[1]
        import os
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.pop("STOCK_ARCHIVE_KEY_HEX", None)
        env.pop("PYTHONPATH", None)
        run = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2021_22_traded_240_warmup_readonly", "--help"],
            cwd=repo, env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--archive-2021", run.stdout)
        self.assertIn("--source-report", run.stdout)


if __name__ == "__main__":
    unittest.main()
