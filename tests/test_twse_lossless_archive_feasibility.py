"""Proof: original numeric strings, source provenance and rows survive gzip exactly."""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import TestCase

from scripts import twse_lossless_archive_feasibility as a


def row(day, code, *, source=a.SOURCE):
    return {
        "market": "twse", "stock_id": code, "trade_date": day,
        "open": Decimal("100.5000"), "high": Decimal("103.100"),
        "low": Decimal("98.500"), "close": Decimal("100.250"),
        "volume": 1150044, "turnover": Decimal("117670133.000"),
        "price_change": Decimal("-0.2500"), "transactions": 28731,
        "source": source,
        "retrieved_at": datetime(2026, 11, 22, 3, 30, 22, 123456,
                                 tzinfo=timezone.utc),
    }


class LosslessArchiveSafetyTests(TestCase):
    def test_exact_decimal_and_source_vintage_roundtrip(self):
        rows = [row(date(2026, 11, 19), "1101"),
                row(date(2026, 11, 19), "2330"),
                row(date(2026, 11, 20), "1101"),
                row(date(2026, 11, 20), "2330")]
        report = a.prove(rows)
        self.assertEqual(report["sample_rows"], 4)
        self.assertEqual(report["sample_distinct_trade_dates"], 2)
        self.assertGreater(report["canonical_jsonl_bytes"], report["gzip_compressed_bytes"])
        self.assertTrue(report["restored_rows_equal_original_including_exact_decimal_and_vintage"])
        self.assertTrue(report["compressed_size_is_not_neon_pg_storage_savings"])
        self.assertTrue(report["same_sample_is_not_a_durable_backup"])
        self.assertEqual(report["production_neon_rows_written"], 0)
        self.assertEqual(report["production_neon_indexes_dropped"], 0)
        self.assertFalse(report["raw_or_compressed_price_rows_uploaded_to_public_repository"])
        self.assertFalse(report["production_migration_approved"])
        self.assertFalse(report["live_trading_approved"])

    def test_fail_closed_on_unsorted_duplicate_unknown_and_inexact_price(self):
        good = row(date(2026, 11, 20), "2330")
        for bad in (
            [good, deepcopy(good)],
            [row(date(2026, 11, 20), "2330"),
             row(date(2026, 11, 19), "1101")],
        ):
            with self.assertRaises(ValueError):
                a.prove(bad)
        for name, value in (
            ("source", "UNKNOWN"),
            ("market", "tpex"),
            ("open", 100.5),
            ("volume", 3.5),
            ("stock_id", "1589永冠"),
            ("retrieved_at", datetime(2026,11,22)),
            ("trade_date", "2026-11-20"),
        ):
            x = deepcopy(good)
            x[name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                a.prove([x])
        with self.assertRaises(ValueError):
            a.prove([])
        with self.assertRaises(ValueError):
            a.prove([good], min_rows=1000)

    def test_never_upgrades_research_or_persists_source_data(self):
        self.assertIn("official_current_listed o", a.READ_ONLY_QUERY)
        self.assertIn("model_stock_exclusions", a.READ_ONLY_QUERY)
        self.assertIn("p.market='twse'", a.READ_ONLY_QUERY)
        self.assertIn("p.source='TWSE_MI_INDEX_ALLBUT0999'", a.READ_ONLY_QUERY)
        for bad in ("INSERT INTO", "UPDATE ", "DELETE FROM", "TRUNCATE ",
                    "DROP INDEX", "CREATE INDEX"):
            self.assertNotIn(bad, a.READ_ONLY_QUERY.upper())
        self.assertLessEqual(a.MAX_SAMPLE_ROWS, 10000)
        self.assertLessEqual(a.MAX_SAMPLE_CALENDAR_DAYS, 10)
        with self.assertRaisesRegex(ValueError, "bounded"):
            a.sample_readonly("fake",start=date(2026, 11, 1),end=date(2026, 11, 20))
        with self.assertRaisesRegex(ValueError, "bounded"):
            a.sample_readonly("",start=date(2026, 11, 19),end=date(2026, 11, 20))


if __name__ == "__main__":
    import unittest
    unittest.main()
