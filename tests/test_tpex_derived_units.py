"""Source-specific volume unit tests: old TPEx raw rows remain unchanged."""
from contextlib import nullcontext
from decimal import Decimal
from unittest import TestCase

from src import build_adjusted_prices as adjusted


class FakeCursor:
    def __init__(self, parent):
        self.parent = parent
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def execute(self, statement, params=None):
        self.parent.selects.append((statement, params))
    def fetchall(self):
        statement = self.parent.selects[-1][0]
        if "FROM daily_prices" in statement:
            return self.parent.raw
        if "FROM corporate_actions" in statement:
            return []
        raise AssertionError("Unexpected query")
    def executemany(self, statement, rows):
        if "daily_adjusted_prices" not in statement:
            raise AssertionError("Only derived price tables may be written")
        self.parent.saved.extend(rows)


class FakeConnection:
    def __init__(self, raw):
        self.raw = raw
        self.saved = []
        self.selects = []
    def cursor(self):
        return FakeCursor(self)
    def transaction(self):
        return nullcontext()


def bar(day, volume, turnover, source, *, market="tpex"):
    return {
        "market": market, "stock_id": "6488", "trade_date": day,
        "open": 100, "high": 110, "low": 90, "close": 105,
        "volume": volume, "turnover": turnover,
        "price_change": 5, "transactions": 20, "source": source,
    }


class TPExDerivedUnitsTests(TestCase):
    def test_original_monthly_units_normalized_only_in_adjusted_rows(self):
        raw = [
            bar("2026-11-18", 9367, Decimal("5047518"),
                "TPEX_TRADING_STOCK"),
            bar("2026-11-19", 9738, Decimal("4906510"),
                "TPEX_TRADING_STOCK"),
            bar("2026-11-20", 7958762, Decimal("3920000000"),
                "TPEX_DAILY_CLOSE_OPENAPI"),
        ]
        conn = FakeConnection(raw)
        self.assertEqual(adjusted.build(conn, "tpex", "6488"), 3)
        self.assertIn("source FROM daily_prices", conn.selects[0][0])
        self.assertEqual([x["volume"] for x in conn.saved],
                         [9367000.0, 9738000.0, 7958762.0])
        self.assertEqual(conn.saved[0]["turnover"], Decimal("5047518000"))
        self.assertEqual(conn.saved[1]["turnover"], Decimal("4906510000"))
        self.assertEqual(raw[0]["volume"], 9367)
        self.assertEqual(raw[0]["turnover"], Decimal("5047518"))

    def test_all_already_normalized_sources_are_unchanged(self):
        for source in adjusted.ALREADY_IN_SHARES_TPEX_SOURCES:
            original = bar("2026-11-18", 9110000, 5050000000, source)
            record = adjusted.normalize_source_units([original], "tpex")[0]
            self.assertEqual(record["volume"], original["volume"])
            self.assertEqual(record["turnover"], original["turnover"])
            self.assertIsNot(record, original)
        source = bar("2026-11-18", 9367, 5047518, "TWSE_STOCK_DAY",
                     market="twse")
        result = adjusted.normalize_source_units([source], "twse")[0]
        self.assertEqual(result["volume"], 9367)

    def test_invalid_source_units_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Unknown TPEx"):
            adjusted.normalize_source_units(
                [bar("2026-11-18", 900, 1000, "UNKNOWN")], "tpex")
        for value in (-1, "0.0001", "NaN", "Infinity", "garbage",
                      "999999999999999999999"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    adjusted.normalize_source_units(
                        [bar("2026-11-18", value, 1000,
                             "TPEX_TRADING_STOCK")], "tpex")

    def test_no_source_missing_is_not_assumed_shares(self):
        broken = bar("2026-11-18", 700, 3000, None)
        with self.assertRaisesRegex(ValueError, "Unknown TPEx"):
            adjusted.normalize_source_units([broken], "tpex")
