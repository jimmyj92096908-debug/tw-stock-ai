import unittest
from unittest.mock import Mock
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.preflight_five_year_history import (
    build_preflight,
    closed_dates_from_payload,
    expected_sessions,
    fetch_closed_dates,
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

    def test_fetch_uses_official_historical_json_endpoint_and_roc_year(self):
        response = Mock()
        response.json.return_value = {
            "stat": "ok",
            "queryYear": "113",
            "title": "113 年市場開休市日期",
            "date": "20240101",
            "data": [["2024-01-01", "中華民國開國紀念日", "依規定放假1日。"]],
        }
        response.raise_for_status.return_value = None
        response.content = b'{\"stat\":\"ok\"}'
        session = Mock()
        session.get.return_value = response

        self.assertEqual(fetch_closed_dates(2024, session), {date(2024, 1, 1)})
        args, kwargs = session.get.call_args
        self.assertIn("/holidaySchedule/holidaySchedule", args[0])
        self.assertEqual(kwargs["params"], {"date": "2024", "response": "json"})
        self.assertEqual(kwargs["timeout"], (8, 20))

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


    def test_preflight_reports_unverified_no_data_separately(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.jsonl").write_text(
                '{"market":"twse","trade_date":"2026-11-19","status":"no_data_unverified"}\n',
                encoding="utf-8",
            )
            report = build_preflight(
                date(2026, 11, 19),
                date(2026, 11, 19),
                {2026: set()},
                root,
            )
        self.assertEqual(report["market_counts"]["twse"]["no_data_unverified"], 1)
        self.assertEqual(report["market_counts"]["twse"]["failed"], 0)
        self.assertEqual(report["no_data_unverified_market_dates"], [
            {"market": "twse", "trade_date": "2026-11-19"}
        ])

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
