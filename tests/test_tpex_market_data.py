import unittest

from src.tpex_market_data import parse_raw_row


class TestTpexRawRow(unittest.TestCase):
    def test_valid_row(self):
        row = [
            "115/10/01", "1,000", "100,000", "100.0",
            "105.0", "99.0", "102.0", "2.0", "50",
        ]
        parsed = parse_raw_row("1295", row)
        self.assertEqual(parsed["open"], 100)
        self.assertEqual(parsed["high"], 105)
        self.assertEqual(parsed["low"], 99)
        self.assertEqual(parsed["close"], 102)
        self.assertEqual(parsed["trade_date"], "2026-10-01")

    def test_rejects_close_above_high(self):
        row = [
            "114/11/03", "403", "44,994", "107.5",
            "114.5", "107.0", "845.5", "0.0", "10",
        ]
        with self.assertRaisesRegex(ValueError, "OHLC"):
            parse_raw_row("1295", row)

    def test_rejects_high_below_low(self):
        row = [
            "114/11/14", "213", "20,729", "98.1",
            "0.79", "96.1", "96.1", "0.0", "10",
        ]
        with self.assertRaisesRegex(ValueError, "OHLC"):
            parse_raw_row("1295", row)

    def test_skips_short_row(self):
        self.assertIsNone(parse_raw_row("1295", ["114/11/03", "100"]))


if __name__ == "__main__":
    unittest.main()
