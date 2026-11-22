"""2024 corporate-action data completeness is a strict release blocker."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_2024_corporate_action_readiness as a

SAMPLE = {
    "eligible_stocks": 894, "all_event_rows": 4,
    "verified_events": 4, "unverified_events": 0,
    "stocks_with_verified_event": 2,
    "total_adjusted_table_bars": 4840,
    "adjusted_status_bars": 484,
    "unadjusted_status_bars": 4356,
    "stocks_with_adjusted_table_rows": 20,
    "stocks_with_adjusted_status": 2,
}


class DividendCoverageGateTests(TestCase):
    def test_truthfully_reports_gaps_and_blocks_model(self):
        report = a.assess_counts(SAMPLE)
        self.assertEqual(report["total_eligible_raw_price_bars"], 894*242)
        self.assertEqual(report["verified_corporate_action_events"], 4)
        self.assertEqual(report["cohort_stocks_with_at_least_one_verified_action"], 2)
        self.assertEqual(report["cohort_stocks_with_at_least_one_adjusted_status"], 2)
        self.assertFalse(report["all_stocks_total_return_labels_validated"])
        self.assertFalse(report["issuer_with_zero_record_proven_to_have_zero_dividends"])
        self.assertFalse(report["historical_asof_issuer_membership_verified"])
        self.assertFalse(report["research_model_allowed_to_train_on_unverified_total_return_labels"])
        self.assertFalse(report["production_live_signal_release_approved"])
        self.assertEqual(report["neon_database_writes"], 0)
        self.assertEqual(report["line_messages_sent"], 0)
        self.assertNotIn("stock_id", report)

    def test_incomplete_or_contradictory_postgres_counts_refused(self):
        for key, value in (
            ("eligible_stocks", 500),
            ("eligible_stocks", 1200),
            ("verified_events", -1),
            ("verified_events", 200),
            ("stocks_with_verified_event", 50),
            ("stocks_with_adjusted_status", 30),
            ("total_adjusted_table_bars", 300000),
            ("adjusted_status_bars", 100000),
        ):
            sample = dict(SAMPLE)
            sample[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                a.assess_counts(sample)
        bad = dict(SAMPLE)
        del bad["unverified_events"]
        with self.assertRaises(ValueError):
            a.assess_counts(bad)
        with self.assertRaises(ValueError):
            a.assess_counts(None)

    def test_positive_appearing_coverage_still_cannot_claim_complete_asof_events(self):
        everything = dict(SAMPLE)
        everything.update({
            "eligible_stocks": 850, "all_event_rows": 850,
            "verified_events": 850, "unverified_events": 0,
            "stocks_with_verified_event": 850,
            "total_adjusted_table_bars": 850*242,
            "adjusted_status_bars": 850*242,
            "unadjusted_status_bars": 0,
            "stocks_with_adjusted_table_rows": 850,
            "stocks_with_adjusted_status": 850,
        })
        proof = a.assess_counts(everything)
        self.assertFalse(proof["source_announcement_vintage_asof_each_signal_proven"])
        self.assertFalse(proof["dividend_and_split_factors_independently_verified"])
        self.assertFalse(proof["production_live_signal_release_approved"])

    def test_readonly_same_snapshot_and_aggregate_only_output(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchone.return_value = dict(SAMPLE)
        with TemporaryDirectory() as td, patch("psycopg.connect",return_value=conn) as dial:
            path = Path(td) / "private-aggregate-only.json"
            proof = a.run_readonly("postgresql://synthetic", output=path)
            self.assertEqual(json.loads(path.read_text()), proof)
            self.assertNotIn('"stock_id"',path.read_text())
            self.assertFalse(proof["production_live_signal_release_approved"])
            self.assertIn("default_transaction_read_only=on", dial.call_args.kwargs["options"])
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.assertEqual(conn.execute.call_args_list[2].args[0], a.COVERAGE_SQL)

    def test_official_allowlist_source_exclusions_and_no_writable_sql(self):
        q = a.COVERAGE_SQL
        self.assertIn("official_current_listed",q)
        self.assertIn("model_stock_exclusions",q)
        self.assertIn("p.stock_id <> '1589'",q)
        self.assertIn("p.source='TWSE_MI_INDEX_ALLBUT0999'",q)
        self.assertIn("corporate_actions",q)
        self.assertIn("daily_adjusted_prices",q)
        for prohibited in ("INSERT INTO", "UPDATE ", "DELETE FROM", "TRUNCATE ",
                           "DROP ", "CREATE "):
            self.assertNotIn(prohibited,q.upper())
