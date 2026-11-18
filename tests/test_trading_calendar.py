import unittest
from datetime import date

from src.trading_calendar import closed_dates_from_payload, is_trading_day


class TradingCalendarTests(unittest.TestCase):
    def test_marks_official_holiday_and_compensatory_day_closed(self):
        payload = {
            "stat": "ok",
            "data": [
                ["2027-01-01", "中華民國開國紀念日", "依規定放假1日。"],
                ["2027-01-04", "國曆新年開始交易日", "國曆新年開始交易。"],
                ["2027-03-01", "和平紀念日", "適逢星期日，於3月1日補假1日。"],
                ["2027-02-01", "農曆春節前最後交易日", "2月2日市場無交易。"],
                ["2027-02-02", "市場無交易，僅辦理結算交割作業。", ""],
            ],
        }
        closed = closed_dates_from_payload(payload)
        self.assertIn(date(2027, 1, 1), closed)
        self.assertNotIn(date(2027, 1, 4), closed)
        self.assertIn(date(2027, 3, 1), closed)
        self.assertIn(date(2027, 2, 2), closed)
        self.assertNotIn(date(2027, 2, 1), closed)

    def test_weekend_closed_even_if_not_listed(self):
        self.assertFalse(is_trading_day(date(2027, 1, 2), set()))

    def test_regular_weekday_open(self):
        self.assertTrue(is_trading_day(date(2027, 1, 4), set()))

    def test_official_holiday_closed(self):
        self.assertFalse(is_trading_day(date(2027, 1, 1), {date(2027, 1, 1)}))

    def test_rejects_bad_status(self):
        with self.assertRaises(ValueError):
            closed_dates_from_payload({"stat": "很抱歉", "data": []})


if __name__ == "__main__":
    unittest.main()
