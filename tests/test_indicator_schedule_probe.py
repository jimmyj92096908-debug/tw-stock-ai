"""Offline contracts for safe independent indicator schedule preview."""
import unittest
from datetime import date
from unittest.mock import patch
from scripts import indicator_schedule_probe as probe


def audit():
    return {
        "latest": {"latest_price_date": "2026-11-19", "latest_score_date": "2026-11-19"},
        "indicator_backlog": [
            {"market": "twse", "eligible": 1085, "pending": 1044, "complete": 41, "unstarted": 942},
            {"market": "tpex", "eligible": 21, "pending": 0, "complete": 21, "unstarted": 0},
        ],
    }


def stock(i, market="twse"):
    return {
        "market": market, "stock_id": str(1300+i),
        "close_days": 100, "latest_close": date(2026, 11, 19),
        "technical_rows": 0, "smc_rows": 0,
        "has_latest_technical": False, "has_latest_smc": False,
    }


class FakeConn:
    def __init__(self):
        self.commands = []

    def execute(self, sql):
        self.commands.append(sql)


class IndicatorScheduleProbeTests(unittest.TestCase):
    def test_aggregate_and_bounded_candidate_probe_never_writes(self):
        conn = FakeConn()
        calls = []
        def select(conn_obj, market, limit):
            calls.append((conn_obj, market, limit))
            return [stock(i) for i in range(20)] if market == "twse" else []
        with (
            patch.object(probe, "collect_audit", return_value=audit()),
            patch.object(probe, "select_candidates", side_effect=select),
        ):
            result = probe.build_probe(conn, captured_at="2026-11-20T10:00:00+00:00")
        self.assertEqual(conn.commands, ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"])
        self.assertEqual([(m, n) for _conn, m, n in calls], [("twse", 20), ("tpex", 20)])
        self.assertEqual(result["pending_total"], 1044)
        self.assertEqual(result["minimum_full_success_batches"], 53)
        self.assertEqual(result["markets"][0]["preview_candidate_count"], 20)
        self.assertFalse(result["indicator_writes_performed"])
        self.assertFalse(result["automatic_write_schedule_activated"])
        self.assertIn("NOT evidence", probe.summary(result))
        self.assertNotIn("1300", str(result))  # ticker picks do not leak into audit artifact

    def test_pending_without_matching_candidates_fails_not_pretends_success(self):
        with (
            patch.object(probe, "collect_audit", return_value=audit()),
            patch.object(probe, "select_candidates", return_value=[]),
        ):
            with self.assertRaisesRegex(ValueError, "mismatch"):
                probe.build_probe(FakeConn())

    def test_bad_candidates_are_rejected(self):
        candidates = [stock(i) for i in range(20)]
        for bad in (
            {**candidates[0], "stock_id": "1808"},
            {**candidates[0], "close_days": 59},
            {**candidates[0], "technical_rows": 100, "smc_rows": 100,
             "has_latest_technical": True,
             "has_latest_smc": True},
            {**candidates[0], "market": "tpex"},
            {**candidates[0], "stock_id": candidates[1]["stock_id"]},
        ):
            supplied = [bad, *candidates[1:]]
            with (
                patch.object(probe, "collect_audit", return_value=audit()),
                patch.object(probe, "select_candidates",
                             side_effect=lambda conn, market, limit:
                             supplied if market == "twse" else []),
            ):
                with self.assertRaisesRegex(ValueError, "contract"):
                    probe.build_probe(FakeConn())

    def test_stale_latest_date_with_high_row_counts_remains_eligible(self):
        candidates=[stock(i) for i in range(20)]
        candidates[0].update({
            "stock_id": "8937",
            "technical_rows": 105, "smc_rows": 106,
            "has_latest_technical": False,
            "has_latest_smc": False,
        })
        with (
            patch.object(probe,"collect_audit",return_value=audit()),
            patch.object(probe,"select_candidates",
                         side_effect=lambda conn,market,limit:
                         candidates if market == "twse" else []),
        ):
            result=probe.build_probe(FakeConn())
        self.assertEqual(result["markets"][0]["preview_candidate_count"],20)
        self.assertEqual(result["pending_total"],1044)

    def test_bad_backlog_counts_fail_closed(self):
        for mutation in ("unbalanced", "negative", "duplicate", "unstarted"):
            broken = audit()
            if mutation == "unbalanced":
                broken["indicator_backlog"][0]["pending"] = 1043
            elif mutation == "negative":
                broken["indicator_backlog"][0]["pending"] = -1
            elif mutation == "unstarted":
                broken["indicator_backlog"][0]["unstarted"] = 1045
            else:
                broken["indicator_backlog"].append(dict(broken["indicator_backlog"][0]))
            with patch.object(probe, "collect_audit", return_value=broken):
                with self.assertRaises(ValueError):
                    probe.build_probe(FakeConn())

    def test_no_price_date_or_missing_evidence_causes_failure(self):
        for broken in ({**audit(), "latest": {"latest_price_date": None}},
                       {**audit(), "indicator_backlog": []}):
            with patch.object(probe, "collect_audit", return_value=broken):
                with self.assertRaises(ValueError):
                    probe.build_probe(FakeConn())

    def test_no_connection_without_database_url(self):
        with self.assertRaisesRegex(ValueError, "DATABASE_URL"):
            probe.run("")

    def test_script_never_calls_apply_or_indicator_writers(self):
        source = __import__("inspect").getsource(probe)
        self.assertIn("READ ONLY", source)
        self.assertNotIn("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED", source)
        self.assertNotIn("--apply", source)
        self.assertNotIn("calculate_technical_stock(", source)
        self.assertNotIn("calculate_smc_stock(", source)


if __name__ == "__main__":
    unittest.main()
