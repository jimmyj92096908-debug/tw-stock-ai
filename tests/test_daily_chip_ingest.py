"""Tests for expanded TWSE 2330 daily chip tracking, without network or DB."""
import unittest
from unittest.mock import patch

from src import institutional_data, margin_data, daily_chip_ingest


class DailyChipStockCohortTests(unittest.TestCase):
    def test_2330_is_in_both_tracked_twse_feeds(self):
        self.assertIn("2330", institutional_data.STOCKS["twse"])
        self.assertIn("2330", margin_data.STOCKS["twse"])
        self.assertEqual(institutional_data.STOCKS["tpex"], {"8937"})
        self.assertEqual(sum(len(s) for s in institutional_data.STOCKS.values()), 5)

    def test_2330_inst_parses_official_twse_columns(self):
        fields = ["證券代號", *institutional_data.TWSE_FIELDS.values()]
        payload = {
            "stat": "OK", "fields": fields,
            "data": [["2330", *(["1"] * len(institutional_data.TWSE_FIELDS))]],
        }
        parsed = institutional_data.parse_twse(payload, "2026-11-20")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["stock_id"], "2330")
        self.assertEqual(parsed[0]["market"], "twse")

    def test_2330_margin_parses_official_twse_table(self):
        fields = ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
                  "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額",
                  "今日餘額", "次一營業日限額"]
        payload = {
            "stat": "OK", "date": "20261120",
            "tables": [{
                "fields": fields,
                "data": [["2330", "台積電", "100", "50", "0", "900", "950", "1000",
                          "10", "20", "0", "200", "190", "1000"]],
            }],
        }
        parsed = margin_data.parse_twse(payload, "2026-11-20")
        self.assertEqual([r["stock_id"] for r in parsed], ["2330"])
        self.assertEqual(parsed[0]["margin_balance"], 950)

    def test_main_requires_five_institutional_rows_before_writing(self):
        tracked = [{"stock_id": s} for s in ("2330", "6213", "4919", "7827", "8937")]
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://invalid.example/db"}), \
             patch("src.daily_chip_ingest.latest_tpex_trade_date",
                   return_value="2026-11-20"), \
             patch("src.daily_chip_ingest.fetch_institutional",
                   return_value=tracked) as fetch, \
             patch("src.daily_chip_ingest.save_institutional", return_value=5) as save, \
             patch("src.daily_chip_ingest.fetch_margin", return_value=tracked), \
             patch("src.daily_chip_ingest.save_margin", return_value=5):
            daily_chip_ingest.main()
        fetch.assert_called_once_with("2026-11-20")
        save.assert_called_once_with(tracked)

    def test_main_refuses_partial_institutional_snapshot(self):
        partial = [{"stock_id": s} for s in ("6213", "4919", "7827", "8937")]
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://invalid.example/db"}), \
             patch("src.daily_chip_ingest.latest_tpex_trade_date",
                   return_value="2026-11-20"), \
             patch("src.daily_chip_ingest.fetch_institutional",
                   return_value=partial), \
             patch("src.daily_chip_ingest.save_institutional") as save:
            with self.assertRaisesRegex(RuntimeError, "應為 5 檔"):
                daily_chip_ingest.main()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
