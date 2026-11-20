"""Offline acceptance for the authorized first indicator -> score transition."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import verify_scored_indicator_pilot as score


def rows(scored=False):
    result = []
    for code in ("1626", "1702"):
        result.append({
            "market": "twse", "stock_id": code,
            "trade_date": date(2026,11,19), "raw_close": 15.2,
            "ma5": 15.0, "ma20": 14.9, "ma60": 14.8,
            "trend_direction": -1,
            "total_score": 62.0 if scored else None,
            "coverage_weight": 0.6 if scored else None,
            "score_date": date(2026,11,19) if scored else None,
        })
    return result


class IndicatorScoreFirstBatchTests(unittest.TestCase):
    def test_transition_verifies_two_real_stock_ids_without_trade_signals(self):
        before = score.snapshot(rows(), phase="before")
        after = score.snapshot(rows(scored=True), phase="after")
        result = score.compare(before, after)
        self.assertEqual(result["newly_scored_stocks"], 2)
        self.assertEqual(result["date"], "2026-11-19")
        self.assertTrue(result["verified"])
        self.assertFalse(result["trading_approved"])
        self.assertFalse(after["trade_signals_enabled"])
        self.assertFalse(after["line_messages_sent"])

    def test_no_score_progress_must_not_be_reported_as_success(self):
        before = score.snapshot(rows(scored=True), phase="before")
        after = score.snapshot(rows(scored=True), phase="after")
        with self.assertRaisesRegex(ValueError, "No newly"):
            score.compare(before, after)

    def test_missing_after_score_fails_closed(self):
        incomplete = rows(scored=True)
        incomplete[1]["total_score"] = None
        with self.assertRaisesRegex(ValueError, "lack valid"):
            score.snapshot(incomplete, phase="after")

    def test_missing_newest_technicals_or_smc_fails(self):
        for field in ("ma5","ma20","ma60","trend_direction"):
            broken = rows()
            broken[0][field] = None
            with self.assertRaisesRegex(ValueError, "Indicators incomplete"):
                score.snapshot(broken, phase="before")

    def test_missing_or_stale_daily_price_fails(self):
        broken = rows()
        broken[0]["raw_close"] = None
        with self.assertRaisesRegex(ValueError, "price"):
            score.snapshot(broken, phase="before")
        broken = rows(scored=True)
        broken[0]["score_date"] = date(2026, 11, 18)
        with self.assertRaisesRegex(ValueError, "lack valid"):
            score.snapshot(broken, phase="after")

    def test_wrong_symbols_and_duplicate_inputs_rejected(self):
        missing = rows()[:1]
        with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
            score.snapshot(missing, phase="before")
        unexpected = rows()
        unexpected[0]["stock_id"] = "9999"
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            score.snapshot(unexpected, phase="before")
        duplicate = rows()
        duplicate[1]["stock_id"] = "1626"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            score.snapshot(duplicate, phase="before")

    def test_market_day_changed_must_block(self):
        before = score.snapshot(rows(), phase="before")
        after = score.snapshot(rows(scored=True), phase="after")
        after["date"] = "2026-11-20"
        with self.assertRaisesRegex(ValueError, "Market date"):
            score.compare(before, after)

    def test_readonly_phase_and_evidence_version_enforced(self):
        before = score.snapshot(rows(), phase="before")
        after = score.snapshot(rows(scored=True), phase="after")
        before["read_only"] = False
        with self.assertRaisesRegex(ValueError, "Read-only"):
            score.compare(before, after)
        before["read_only"] = True
        after["schema_version"] = 99
        with self.assertRaisesRegex(ValueError, "schema"):
            score.compare(before, after)

    def test_sql_targets_exact_latest_session_and_no_mutation(self):
        query = score.QUERY.upper()
        self.assertIn("1626", score.QUERY)
        self.assertIn("1702", score.QUERY)
        self.assertIn("MAX(TRADE_DATE)", query)
        self.assertIn("DAILY_TECHNICALS", query)
        self.assertIn("DAILY_SMC", query)
        self.assertIn("DAILY_COMPOSITE_SCORES", query)
        for keyword in ("INSERT INTO","DELETE FROM","UPDATE PUBLIC","TRUNCATE","DROP TABLE"):
            self.assertNotIn(keyword, query)
        self.assertIn("SET TRANSACTION READ ONLY", Path(score.__file__).read_text())

    def test_no_database_url_is_accepted(self):
        with self.assertRaisesRegex(ValueError, "DATABASE_URL"):
            score.fetch("", phase="before")


if __name__ == "__main__":
    unittest.main()
