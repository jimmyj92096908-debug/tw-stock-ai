import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.preflight_five_year_history import (
    build_preflight,
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
        with self.assertRaisesRegex(ValueError, "different calendar year"):
            closed_dates_from_payload({"stat": "ok", "queryYear": 114, "data": []}, 2026)

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

    def test_calendar_fetch_uses_roc_year_and_cache_buster(self):
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"stat": "ok", "queryYear": 113, "data": []}

        class Session:
            def get(self, url, params, **kwargs):
                self.params = params
                return Response()

        session = Session()
        self.assertEqual(fetch_closed_dates(2024, session), set())
        self.assertEqual(session.params["queryYear"], "113")
        self.assertTrue(session.params["_"])


if __name__ == "__main__":
    unittest.main()
