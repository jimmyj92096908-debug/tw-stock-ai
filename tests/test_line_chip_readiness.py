"""Offline permission and date checks for optional LINE chip score display."""
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from scripts import line_chip_readiness as readiness


def grants(**overrides):
    row = {
        "connected_database": "twstock",
        "reader_role_exists": True,
        "public_schema_usage": True,
        "missing_chip_select_columns": list(readiness.REQUIRED_COLUMNS),
        "any_private_line_message_select": False,
        "whole_private_line_message_select": False,
    }
    row.update(overrides)
    return row


def dates(**overrides):
    row = {
        "price_date": date(2026, 11, 20),
        "technical_date": date(2026, 11, 19),
        "composite_date": date(2026, 11, 19),
        "independently_publishable_chip_date": date(2026, 11, 20),
        "independently_publishable_chip_score": Decimal("40.65"),
        "chip_source_coverage": Decimal("0.65"),
    }
    row.update(overrides)
    return row


def inspect(grant_row=None, date_row=None):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        grants() if grant_row is None else grant_row,
        dates() if date_row is None else date_row,
    ]
    return readiness.inspect_readiness(conn), cursor


class LineChipReadinessTests(unittest.TestCase):
    def test_existing_ungranted_role_is_blocked_but_score_exists(self):
        report, cur = inspect()
        self.assertEqual(report["assessment"], "blocked_or_inconclusive")
        self.assertEqual(report["missing_chip_select_columns"],
                         sorted(readiness.REQUIRED_COLUMNS))
        self.assertEqual(report["standalone_chip_date"], "2026-11-20")
        self.assertEqual(report["standalone_chip_score"], 40.65)
        self.assertEqual(report["standalone_source_coverage"], .65)
        self.assertTrue(report["chip_valid_for_price"])
        self.assertFalse(report["production_database_modified"])
        self.assertFalse(report["line_messages_sent"])
        self.assertFalse(report["webhook_cutover_approved"])
        self.assertFalse(report["new_gateway_enabled_verified"])
        self.assertEqual(cur.execute.call_count, 2)
        self.assertEqual(cur.execute.call_args_list[0].args[1],
                         (list(readiness.REQUIRED_COLUMNS),))

    def test_all_required_columns_present_is_not_cutover_approval(self):
        report, _ = inspect(grants(missing_chip_select_columns=[]))
        self.assertEqual(report["assessment"],
                         "optional_chip_read_query_preflight_pass")
        self.assertFalse(report["webhook_cutover_approved"])
        self.assertFalse(report["new_gateway_enabled_verified"])

    def test_any_private_line_read_right_blocks_release(self):
        for category in ("any_private_line_message_select",
                         "whole_private_line_message_select"):
            with self.subTest(category=category):
                report, _ = inspect(grants(missing_chip_select_columns=[],
                                           **{category: True}))
                self.assertEqual(report["assessment"], "blocked_or_inconclusive")
                self.assertTrue(report["private_line_message_read_privilege_detected"])

    def test_stale_composite_is_distinct_from_valid_new_chip(self):
        report, _ = inspect(grants(missing_chip_select_columns=[]))
        self.assertEqual(report["technical_date"], "2026-11-19")
        self.assertEqual(report["composite_date"], "2026-11-19")
        self.assertEqual(report["standalone_chip_date"], "2026-11-20")
        self.assertTrue(report["chip_valid_for_price"])

    def test_future_chip_score_cannot_pass_price_asof_guard(self):
        report, _ = inspect(
            grants(missing_chip_select_columns=[]),
            dates(price_date=date(2026, 11, 19))
        )
        self.assertFalse(report["chip_valid_for_price"])
        self.assertEqual(report["assessment"], "blocked_or_inconclusive")

    def test_unavailable_chip_score_is_not_invented(self):
        report, _ = inspect(
            grants(missing_chip_select_columns=[]),
            dates(independently_publishable_chip_date=None,
                  independently_publishable_chip_score=None,
                  chip_source_coverage=None)
        )
        self.assertIsNone(report["standalone_chip_score"])
        self.assertIsNone(report["standalone_source_coverage"])
        self.assertEqual(report["assessment"], "blocked_or_inconclusive")

    def test_wrong_database_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "outside the twstock"):
            inspect(grants(connected_database="postgres"))

    def test_db_introspection_is_read_only_and_does_not_select_private_messages(self):
        self.assertIn("has_column_privilege", readiness.GRANT_CHECK_SQL)
        self.assertIn("has_any_column_privilege", readiness.GRANT_CHECK_SQL)
        self.assertNotIn("FROM public.line_messages",
                         readiness.GRANT_CHECK_SQL)
        self.assertIn("WHERE market='twse' AND stock_id='2330'",
                      readiness.LATEST_DATES_SQL)
        for sql in (readiness.GRANT_CHECK_SQL, readiness.LATEST_DATES_SQL):
            self.assertTrue(sql.lstrip().startswith("SELECT"))
            self.assertNotIn("INSERT INTO", sql)
            self.assertNotIn("UPDATE public.", sql)
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://not-real/test"}), \
             patch("scripts.line_chip_readiness.psycopg.connect") as connect, \
             patch("scripts.line_chip_readiness.inspect_readiness",
                   return_value={"assessment": "blocked_or_inconclusive"}):
            readiness.main()
        self.assertEqual(connect.call_args.kwargs["options"],
                         "-c default_transaction_read_only=on")
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], 15)


if __name__ == "__main__":
    unittest.main()
