"""Test precisely frozen 2022 market days 49-96 and no-write pacing."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_2022_days49_96_source_probe as mod
from tests.test_twse_2022_shared_source_stream import (
    allowed_codes, synthetic_day,
)

DATES = tuple(date.fromisoformat(s) for s in """
2022-03-23 2022-03-24 2022-03-25 2022-03-28 2022-03-29 2022-03-30
2022-03-31 2022-04-01 2022-04-06 2022-04-07 2022-04-08 2022-04-11
2022-04-12 2022-04-13 2022-04-14 2022-04-15 2022-04-18 2022-04-19
2022-04-20 2022-04-21 2022-04-22 2022-04-25 2022-04-26 2022-04-27
2022-04-28 2022-04-29 2022-05-03 2022-05-04 2022-05-05 2022-05-06
2022-05-09 2022-05-10 2022-05-11 2022-05-12 2022-05-13 2022-05-16
2022-05-17 2022-05-18 2022-05-19 2022-05-20 2022-05-23 2022-05-24
2022-05-25 2022-05-26 2022-05-27 2022-05-30 2022-05-31 2022-06-01
""".split())


def connection(days=DATES):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.fetchall.return_value = [(d,) for d in days]
    conn.cursor.return_value = cur
    return conn, cur


class HistoricSecondBatchTests(TestCase):
    def test_calendar_frozen_48_and_holidays(self):
        self.assertEqual(len(DATES), 48)
        self.assertEqual(mod.verify_calendar(DATES), DATES)
        self.assertNotIn(date(2022, 4, 4), DATES)
        self.assertNotIn(date(2022, 4, 5), DATES)
        self.assertNotIn(date(2022, 5, 2), DATES)
        for altered in (
            DATES[:-1], DATES[::-1],
            (date(2022, 3, 22),) + DATES[1:],
            DATES[:12] + (date(2022, 4, 4),) + DATES[13:],
            DATES[:12] + (DATES[12],) + DATES[13:],
            DATES[:12] + (date(2022, 4, 11),) + DATES[13:],
        ):
            with self.subTest(altered=altered[:3]), self.assertRaises(ValueError):
                mod.verify_calendar(altered)

    def test_full_quota_and_readonly_zero_write(self):
        conn, cur = connection()
        seen, sleeps = [], []
        def fetch(day):
            seen.append(day)
            return synthetic_day(day)
        with (
            TemporaryDirectory() as folder,
            patch("psycopg.connect", return_value=conn) as dial,
            patch.object(mod, "load_current_twse_allowed", return_value=allowed_codes()),
            patch.object(mod, "_processed_days", return_value=set()),
        ):
            path = Path(folder) / "aggregate.json"
            data = mod.execute("postgresql://test",
                               fetcher=fetch, sleeper=sleeps.append,
                               output=path)
            self.assertEqual(seen, list(DATES))
            self.assertEqual(sleeps, [4.0] * 47)
            self.assertEqual(data["actual_official_http_requests"], 48)
            self.assertEqual(data["maximum_official_http_requests"], 48)
            self.assertEqual(data["complete_common_stock_cohort"], 650)
            self.assertEqual(data["source_session_ordinal_end"], 96)
            self.assertFalse(data["real_2022_240_day_ma_verified"])
            self.assertEqual(data["neon_rows_written"], 0)
            self.assertEqual(data["line_messages_sent"], 0)
            self.assertFalse(data["live_trading_approved"])
            self.assertNotIn('"stock_id"', path.read_text())
            self.assertEqual(json.loads(path.read_text()), data)
            cur.execute.assert_called_once_with(
                mod.REFERENCE_CALENDAR_SQL,
                (mod.FIRST_DAY, mod.LAST_DAY, mod.DAYS + 1),
            )
            self.assertIn("default_transaction_read_only=on",
                          dial.call_args.kwargs["options"])
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

    def test_unlisted_import_receipt_and_broken_source_stop_before_commit(self):
        for failure in ("calendar", "receipt", "exclusion", "source"):
            conn, cur = connection(DATES[:-1] if failure == "calendar" else DATES)
            seen = []
            def fetch(day):
                seen.append(day)
                return None if failure == "source" and day == DATES[3] else synthetic_day(day)
            with (
                patch("psycopg.connect",return_value=conn),
                patch.object(mod, "load_current_twse_allowed",
                             return_value=allowed_codes() | {("twse","1589")}
                             if failure == "exclusion" else allowed_codes()),
                patch.object(mod, "_processed_days",
                             return_value={DATES[3]} if failure == "receipt" else set()),
            ):
                with self.subTest(failure=failure), self.assertRaises(ValueError):
                    mod.execute("test",fetcher=fetch,sleeper=lambda _:None)
                self.assertEqual(len(seen),4 if failure == "source" else 0)
