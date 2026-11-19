import unittest

from src.technical_indicators import compute_indicators


def sample_rows(count=260):
    rows = []
    for index in range(count):
        close = 100.0 + index
        rows.append({
            "market": "twse",
            "stock_id": "2330",
            "trade_date": f"2026-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}",
            "open": close + 0.5,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000 + index * 10,
        })
    return rows


class TechnicalIndicatorsTests(unittest.TestCase):
    def test_all_nine_moving_averages_have_expected_values(self):
        result = compute_indicators(sample_rows())
        last = result[-1]
        self.assertAlmostEqual(last["ma5"], sum(range(355, 360)) / 5)
        self.assertAlmostEqual(last["ma240"], sum(range(120, 360)) / 240)
        self.assertIsNone(result[238]["ma240"])
        self.assertIsNotNone(result[239]["ma240"])

    def test_rsi_for_continuous_rise_is_100(self):
        result = compute_indicators(sample_rows(20))
        self.assertAlmostEqual(result[14]["rsi14"], 100.0)
        self.assertIsNone(result[13]["rsi14"])

    def test_volume_averages_and_atr(self):
        result = compute_indicators(sample_rows(25))
        self.assertAlmostEqual(result[4]["volume_ma5"], sum(1000 + i * 10 for i in range(5)) / 5)
        self.assertIsNone(result[18]["volume_ma20"])
        self.assertIsNotNone(result[19]["volume_ma20"])
        self.assertAlmostEqual(result[13]["atr14"], 4.0)

    def test_duplicate_or_unsorted_dates_are_rejected(self):
        rows = sample_rows(3)
        rows[2]["trade_date"] = rows[1]["trade_date"]
        with self.assertRaises(ValueError):
            compute_indicators(rows)

    def test_invalid_ohlc_row_is_excluded_without_aborting_series(self):
        rows = sample_rows(20)
        rows[5]["close"] = rows[5]["high"] + 1
        result = compute_indicators(rows)
        for field in ("ma5", "ma240", "rsi14", "volume_ma5", "volume_ma20", "atr14"):
            self.assertIsNone(result[5][field])
        self.assertIsNotNone(result[6]["ma5"])

    def test_empty_input(self):
        self.assertEqual(compute_indicators([]), [])

    def test_missing_ohlc_rows_do_not_invalidate_later_price_indicators(self):
        rows = sample_rows(260)
        rows[100]["high"] = None
        rows[100]["low"] = None
        rows[100]["close"] = None
        result = compute_indicators(rows)

        # Missing-price date stays blank; later valid observations resume normally.
        for field in ("ma5", "ma240", "rsi14", "atr14"):
            self.assertIsNone(result[100][field])
            self.assertIsNotNone(result[101][field] if field != "ma240" else result[-1][field])

        self.assertIsNotNone(result[-1]["ma240"])
        self.assertIsNotNone(result[-1]["rsi14"])
        self.assertIsNotNone(result[-1]["atr14"])
        # 成交量雖然大於 0，但缺少 OHLC 的資料不得污染量均線。
        self.assertIsNone(result[100]["volume_ma5"])
        self.assertIsNotNone(result[101]["volume_ma5"])


if __name__ == "__main__":
    unittest.main()
