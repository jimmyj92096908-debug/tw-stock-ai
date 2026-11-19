import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.preflight_five_year_history import (
    build_preflight,
    closed_dates_from_html,
    closed_dates_from_payload,
    expected_sessions,
    fetch_closed_dates,
    read_latest_manifest,
)


class FiveYearHistoryPreflightTests(unittest.TestCase):
    def test_calendar_closed_days_are_parsed_from_official_payload(self):
        payload = {
            "stat": "ok",
            "queryYear": 115,
            "title": "115 年市場開休市日期",
            "date": "20260101",
            "data": [
                ["2026-01-01", "開國紀念日", "放假一天"],
                ["2026-01-02", "市場交易日", "正常交易"],
            ],
        }
        self.assertEqual(
            closed_dates_from_payload(payload, 2026),
            {date(2026, 1, 1)},
        )

    def test_expected_sessions_excludes_weekends_and_official_closures(self):
        closed = {2026: {date(2026, 1, 1)}}
        result = expected_sessions(date(2025, 12, 31), date(2026, 1, 5), closed)
        self.assertEqual(
            [d.isoformat() for d in result],
            ["2025-12-31", "2026-01-02", "2026-01-05"],
        )

    def test_manifest_latest_status_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.jsonl"
            path.write_text(
                json.dumps({"market": "twse", "trade_date": "2026-01-02", "status": "failed"})
                + "\n"
                + json.dumps({"market": "twse", "trade_date": "2026-01-02", "status": "success"})
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(read_latest_manifest(path)[("twse", "2026-01-02")]["status"], "success")

    def test_preflight_is_read_only_and_counts_missing_market_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            report = build_preflight(
                date(2026, 1, 2),
                date(2026, 1, 5),
                {2026: set()},
                Path(temp),
            )
            self.assertEqual(report["official_trading_session_count"], 2)
            self.assertEqual(report["expected_market_date_tasks"], 4)
            self.assertEqual(report["market_counts"]["twse"]["pending"], 2)
            self.assertFalse(report["daily_quote_downloaded"])
            self.assertFalse(report["database_modified"])
            self.assertEqual(report["stock_universe_validation"]["status"], "not_run")

    def test_success_manifest_requires_both_nonempty_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw/twse/2026-01-02.json.gz"
            rows = root / "rows/twse/2026-01-02.jsonl"
            raw.parent.mkdir(parents=True)
            rows.parent.mkdir(parents=True)
            raw.write_bytes(b"gzip")
            rows.write_text('{"stock_id":"2330"}\n', encoding="utf-8")
            (root / "manifest.jsonl").write_text(
                json.dumps({
                    "market": "twse", "trade_date": "2026-01-02", "status": "success",
                    "raw_path": "raw/twse/2026-01-02.json.gz",
                    "rows_path": "rows/twse/2026-01-02.jsonl",
                }) + "\n",
                encoding="utf-8",
            )
            report = build_preflight(
                date(2026, 1, 2), date(2026, 1, 2), {2026: set()}, root
            )
            self.assertEqual(report["market_counts"]["twse"]["completed"], 1)
            self.assertEqual(report["market_counts"]["tpex"]["pending"], 1)

    def test_reject_calendar_wrong_year(self):
        with self.assertRaisesRegex(ValueError, "instead of requested"):
            closed_dates_from_payload({"stat": "ok", "queryYear": 115, "title": "116 年市場開休市日期", "date": "20270101", "data": []}, 2026)

    def test_missing_historical_calendar_blocks_expected_and_pending_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            report = build_preflight(
                date(2025, 12, 31),
                date(2026, 1, 5),
                {2026: set()},
                Path(temp),
            )
            self.assertEqual(report["calendar_status"], "incomplete")
            self.assertEqual(report["calendar_unavailable_years"], [2025])
            self.assertIsNone(report["official_trading_session_count"])
            self.assertIsNone(report["expected_market_date_tasks"])
            self.assertIsNone(report["market_counts"]["twse"]["pending"])
            self.assertFalse(report["pending_count_is_authoritative"])

    def test_historical_html_calendar_parses_roc_dates_and_closed_days(self):
        html = """
        <h1>中華民國113年有價證券集中交易市場開（休）市日期表</h1>
        <table><tr><th>名稱</th><th>日期</th><th>星期</th><th>說明</th></tr>
        <tr><td>國曆新年開始交易日</td><td>1月2日</td><td>二</td><td>開始交易</td></tr>
        <tr><td>市場無交易</td><td>2月6日</td><td>二</td><td>僅辦理結算交割</td></tr>
        <tr><td>農曆春節</td><td>2月9日<br>2月10日</td><td>五<br>六</td><td>依規定放假</td></tr>
        </table>
        """
        self.assertEqual(
            closed_dates_from_html(html, 2024),
            {date(2024, 2, 6), date(2024, 2, 9), date(2024, 2, 10)},
        )

    def test_historical_html_preserves_explicit_prior_year_dates(self):
        html = """
        <h1>中華民國111年有價證券集中交易市場開（休）市日期表</h1>
        <table><tr><td>中華民國開國紀念日</td><td>12月31日(110年) 1月1日(111年)</td><td>五 六</td><td>111年1月1日適逢星期六，110年12月31日補假1日。</td></tr></table>
        """
        self.assertEqual(
            closed_dates_from_html(html, 2022),
            {date(2022, 1, 1)},
        )

    def test_calendar_fetch_uses_official_historical_json_endpoint(self):
        class Response:
            def json(self):
                return {
                    "stat": "ok",
                    "queryYear": "113",
                    "title": "113 年市場開休市日期",
                    "date": "20240101",
                    "data": [["2024-02-06", "市場無交易", "僅辦理結算交割"]],
                }
            def raise_for_status(self):
                pass

        class Session:
            def __init__(self):
                self.calls = []
            def get(self, url, params=None, **kwargs):
                self.calls.append((url, params, kwargs))
                return Response()

        session = Session()
        self.assertEqual(fetch_closed_dates(2024, session), {date(2024, 2, 6)})
        self.assertEqual(
            session.calls[0][0],
            "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule",
        )
        self.assertEqual(session.calls[0][1], {"queryYear": "113", "response": "json"})
        self.assertEqual(session.calls[0][2]["timeout"], (8, 20))



if __name__ == "__main__":
    unittest.main()
