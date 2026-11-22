"""Synthetic, no-secret tests for bounded REAL 2021 source-only canary."""
from datetime import date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_2021_two_day_official_source_canary as canary
from tests.test_twse_stateless_2022_source_probe import rows

P = Decimal("100.2500")


def source_rows(day, *, count=720, include_anchor=True):
    original = rows(day, number=count)
    if include_anchor:
        original.append({**original[0], "stock_id": "2330"})
    return original


class Historical2021CanaryTests(TestCase):
    def setUp(self):
        self.roster = {("twse", x["stock_id"])
                       for x in source_rows(canary.FROZEN_DAYS[0])}
        self.anchors = {d: P for d in canary.FROZEN_DAYS}

    def test_two_validated_source_dates_match_separate_2330_anchors(self):
        calls, pauses = [], []
        def fetch(d):
            calls.append(d)
            return source_rows(d)
        receipt = canary.evaluate_source(
            canary.FROZEN_DAYS, self.roster, self.anchors,
            fetcher=fetch, sleeper=pauses.append,
        )
        self.assertEqual(calls, list(canary.FROZEN_DAYS))
        self.assertEqual(pauses, [4.0])
        self.assertEqual(receipt["validated_2330_original_close_anchor_days"], 2)
        self.assertEqual(receipt["source_request_count"], 2)
        self.assertEqual(list(receipt["eligible_current_listed_source_bar_counts"].values()),
                         [721, 721])
        self.assertEqual(receipt["neon_price_or_technical_rows_written"], 0)
        self.assertEqual(receipt["line_messages_sent"], 0)
        self.assertFalse(receipt["live_trading_approved"])
        self.assertFalse(receipt["five_year_history_completed"])

    def test_broken_saved_2330_anchor_refuses_2021_source(self):
        wrong = {**self.anchors, canary.FROZEN_DAYS[1]: Decimal("99.00")}
        with self.assertRaisesRegex(ValueError, "conflicts"):
            canary.evaluate_source(canary.FROZEN_DAYS, self.roster, wrong,
                                   fetcher=source_rows, sleeper=lambda _: None)

    def test_incomplete_market_source_or_missing_2330_is_rejected(self):
        for fetch in (
            lambda d: source_rows(d, count=120),
            lambda d: source_rows(d, include_anchor=False),
        ):
            with self.subTest(fetch=fetch), self.assertRaises(ValueError):
                canary.evaluate_source(canary.FROZEN_DAYS, self.roster,
                                       self.anchors, fetcher=fetch,
                                       sleeper=lambda _: None)

    def test_dates_exclusion_and_request_budget_fail_before_source(self):
        for date_list, roster, pause in (
            (canary.FROZEN_DAYS[::-1], self.roster, 4),
            (canary.FROZEN_DAYS[:1], self.roster, 4),
            (canary.FROZEN_DAYS, self.roster | {("twse", "1589")}, 4),
            (canary.FROZEN_DAYS, self.roster, 0),
        ):
            calls = []
            with self.subTest(date_list=date_list, pause=pause), self.assertRaises(ValueError):
                canary.evaluate_source(date_list, roster, self.anchors,
                                       fetcher=lambda d: calls.append(d),
                                       pause_seconds=pause)
            self.assertEqual(calls, [])

    def test_neon_2330_anchors_require_exact_two_clean_rows_and_read_only(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = [(d, P) for d in canary.FROZEN_DAYS]
        with patch("psycopg.connect", return_value=conn) as connect:
            expected = canary.read_anchors("postgresql://private-fake")
        self.assertEqual(expected, self.anchors)
        self.assertNotIn("options", connect.call_args.kwargs)
        self.assertEqual(conn.execute.call_args_list[0].args[0],
                         "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        self.assertIn("SET LOCAL statement_timeout",conn.execute.call_args_list[1].args[0])
        self.assertEqual(cursor.execute.call_args.args,
                         (canary.ANCHORS_SQL, canary.FROZEN_DAYS))
        for token in ("INSERT INTO", "DELETE FROM", "UPDATE PUBLIC", "DROP TABLE"):
            self.assertNotIn(token,canary.ANCHORS_SQL.upper())
        conn.rollback.assert_called_once()
        for invalid in ([], [(canary.FROZEN_DAYS[0], P)],
                        [(canary.FROZEN_DAYS[1], P), (canary.FROZEN_DAYS[0], P)],
                        [(canary.FROZEN_DAYS[0], Decimal("-1")),
                         (canary.FROZEN_DAYS[1], P)]):
            cursor.fetchall.return_value = invalid
            with patch("psycopg.connect", return_value=conn):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    canary.read_anchors("postgresql://private-fake")

    def test_live_runner_only_uses_frozen_sparse_2021_dates(self):
        with (patch.object(canary, "preflight",return_value=(
                list(canary.FROZEN_DAYS)+[date(2021,12,3)],
                self.roster)) as preflight,
              patch.object(canary, "read_anchors", return_value=self.anchors)):
            receipt = canary.run("postgresql://private-fake",today=date(2026,11,23),
                                 fetcher=source_rows, sleeper=lambda _: None)
        self.assertEqual(receipt["official_source_dates"], ["2021-12-01","2021-12-02"])
        self.assertEqual(preflight.call_args.kwargs["start"], canary.START)
        self.assertEqual(preflight.call_args.kwargs["end"], canary.END)

    def test_missing_2021_sparse_reference_fails_before_any_http_request(self):
        with patch.object(canary, "preflight",return_value=(
                [date(2021,12,2),date(2021,12,3)],self.roster)), \
             patch.object(canary, "read_anchors") as anchors:
            with self.assertRaisesRegex(ValueError,"calendar changed"):
                canary.run("postgresql://fake",today=date(2026,11,23),
                           fetcher=lambda _:self.fail("HTTP request not permitted"))
            anchors.assert_not_called()
