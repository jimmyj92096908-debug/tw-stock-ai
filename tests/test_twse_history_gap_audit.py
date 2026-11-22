"""Verify gap triage never mistakes processed dates for missing dates."""
from datetime import date
from unittest import TestCase
from scripts.twse_history_gap_audit import summarize

class TriageTests(TestCase):
    def test_prioritize_only_unprocessed_undercovered(self):
        rows = [
            (date(2022, 1, 4), 30, 1, 0),
            (date(2022, 1, 5), 60, 0, 0),
            (date(2022, 1, 6), 810, 0, 0),
            (date(2022, 1, 7), 0, 0, 1),
        ]
        out = summarize(rows, minimum=700)
        self.assertEqual(out["unprocessed_undercovered_dates"], 1)
        self.assertEqual(out["priority_dates"],
                         [{"trade_date": "2022-01-05", "observed": 60}])
        self.assertEqual(out["writes"], 0)
        self.assertTrue(out["does_not_prove_listing_history_or_five_year_completion"])

    def test_invalid_limits(self):
        with self.assertRaises(ValueError):
            summarize([], limit=0)
