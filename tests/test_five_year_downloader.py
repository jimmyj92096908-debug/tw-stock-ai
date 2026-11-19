import gzip
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.download_five_year_market_history import (
    download_range,
    is_explicit_no_data_response,
    load_completed,
    trading_weekdays,
)


class FiveYearDownloaderTests(unittest.TestCase):
    def test_weekday_iterator_skips_weekends(self):
        days = list(trading_weekdays(date(2026, 11, 19), date(2026, 11, 23)))
        self.assertEqual([d.isoformat() for d in days], ["2026-11-19", "2026-11-20", "2026-11-23"])

    def test_manifest_resume_skips_completed_market_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.jsonl"
            manifest.write_text(json.dumps({
                "market": "twse", "trade_date": "2026-11-19", "status": "success"
            }) + "\n", encoding="utf-8")
            self.assertIn(("twse", "2026-11-19"), load_completed(manifest))

    def test_download_persists_gzipped_raw_and_normalized_rows(self):
        payload = {
            "stat": "ok",
            "date": "20261119",
            "tables": [{
                "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差"],
                "data": [["2330", "台積電", "1000", "10", "1000000", "1000", "1010", "990", "1005", "5"]],
            }],
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        class FakeResponse:
            content = raw
            def raise_for_status(self): pass
            def json(self): return payload

        class FakeSession:
            headers = {}
            def update_headers(self, value): pass
            def get(self, *args, **kwargs): return FakeResponse()

        with tempfile.TemporaryDirectory() as temp:
            with patch("scripts.download_five_year_market_history.requests.Session", return_value=FakeSession()):
                with patch("scripts.download_five_year_market_history.time.sleep"):
                    counts = download_range(date(2026, 11, 19), date(2026, 11, 19), Path(temp), ["twse"], 0.25)
            self.assertEqual(counts["success"], 1)
            raw_path = Path(temp) / "raw" / "twse" / "2026-11-19.json.gz"
            rows_path = Path(temp) / "rows" / "twse" / "2026-11-19.jsonl"
            self.assertEqual(json.loads(gzip.decompress(raw_path.read_bytes())), payload)
            row = json.loads(rows_path.read_text(encoding="utf-8"))
            self.assertEqual(row["stock_id"], "2330")
            self.assertEqual(row["close"], 1005)
            self.assertEqual(row["ohlc_status"], "complete")


    def test_explicit_no_data_is_not_assumed_to_be_a_holiday(self):
        self.assertTrue(is_explicit_no_data_response({"stat": "很抱歉，沒有符合條件的資料!"}))
        self.assertFalse(is_explicit_no_data_response({"stat": "ok", "data": []}))
        self.assertFalse(is_explicit_no_data_response({"stat": "系統維護中"}))

    def test_unverified_no_data_is_recorded_separately_and_not_resumed_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.jsonl"
            manifest.write_text(json.dumps({
                "market": "twse", "trade_date": "2026-11-19", "status": "no_data_unverified"
            }) + "\\n", encoding="utf-8")
            self.assertNotIn(("twse", "2026-11-19"), load_completed(manifest))

    def test_reject_too_fast_request_rate(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "at least 0.25"):
                download_range(date(2026, 11, 19), date(2026, 11, 19), Path(temp), ["twse"], 0.1)


if __name__ == "__main__":
    unittest.main()
