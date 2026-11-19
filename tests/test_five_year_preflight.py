import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.preflight_five_year_history import (
    build_preflight,
    closed_dates_from_payload,
    expected_sessions,
)


class CalendarParserTests(unittest.TestCase):
    def test_parses_roc_dates_and_excludes_market_closed_rows(self):
        payload = {
            "stat": "ok",
            "queryYear": "115",
            "title": "115 年市場開休市日期",
            "date": "20260101",
            "data": [
                ["115/01/01", "中華民國開國紀念日", "依規定放假1日。"],
                ["115/01/02", "國曆新年開始交易日", "國曆新年開始交易。"],
                ["115/02/12", "市場無交易", "僅辦理結算交割作業"],
            ],
        }
        self.assertEqual(
            closed_dates_from_payload(payload, 2026),
            {date(2026, 1, 1), date(2026, 2, 12)},
        )

    def test_rejects_wrong_year_response(self):
        payload = {"stat": "ok", "queryYear": "115", "title": "116 年市場開休市日期", "date": "20270101", "data": []}
        with self.assertRaises(ValueError):
            closed_dates_from_payload(payload, 2026)

    def test_expected_sessions_excludes_weekends_and_holidays(self):
        closed = {2026: {date(2026, 1, 1)}}
        self.assertEqual(
            expected_sessions(date(2026, 1, 1), date(2026, 1, 5), closed),
            [date(2026, 1, 2), date(2026, 1, 5)],
        )

    def test_incomplete_calendar_does_not_claim_pending_count(self):
        with TemporaryDirectory() as tmp:
            report = build_preflight(
                date(2025, 12, 30),
                date(2026, 1, 5),
                {2026: set()},
                Path(tmp),
            )
        self.assertEqual(report["calendar_status"], "incomplete")
        self.assertIsNone(report["official_trading_session_count"])
        self.assertFalse(report["pending_count_is_authoritative"])


if __name__ == "__main__":
    unittest.main()
