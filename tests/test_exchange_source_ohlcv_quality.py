"""Classify old NULL-quote placeholders and fail closed on impossible OHLCV."""
from unittest import TestCase
from scripts.exchange_source_ohlcv_quality import classify, PRICE_QUALITY_SQL


def row(market="twse", source="TWSE_MI_INDEX_ALLBUT0999", *,
        total=1000, usable=1000, nulls=0, bad_range=0, bad_price=0,
        bad_volume=0):
    return {
        "market": market, "source": source, "total_rows": total,
        "usable_ohlcv_rows": usable, "null_ohlc_rows": nulls,
        "impossible_range_rows": bad_range,
        "nonpositive_price_rows": bad_price,
        "invalid_volume_rows": bad_volume,
    }


class ExchangeSourceQualityTests(TestCase):
    def test_legacy_null_ohlc_not_treated_as_real_bars_or_hallucinated_error(self):
        report = classify([
            row("twse", "TWSE_MI_INDEX_ALLBUT0999"),
            row("twse", "TWSE_STOCK_DAY", total=115, usable=0, nulls=115),
            row("tpex", "TPEX_TRADING_STOCK", total=260, usable=0, nulls=260),
        ])
        self.assertEqual(report["status"], "PASS_UNPRICED_OLD_ROWS_EXPLICIT")
        self.assertEqual(report["totals"]["null_ohlc_rows"], 375)
        self.assertEqual(report["totals"]["usable_ohlcv_rows"], 1000)
        self.assertTrue(report["null_ohlc_is_not_usable_model_history"])
        self.assertEqual(report["database_rows_written"], 0)
        self.assertFalse(report["trading_approved"])
        self.assertFalse(report["historical_asof_listing_membership_proven"])

    def test_impossible_prices_or_unrecognized_provenance_block(self):
        for case in (
            row(total=10, usable=9, bad_range=1),
            row(total=10, usable=9, bad_price=1),
            row("tpex", "TPEX_FAKE_SOURCE", total=10),
            row(total=10, usable=9, bad_volume=1),
        ):
            self.assertEqual(
                classify([case])["status"],
                "BLOCKED_IMPOSSIBLE_OR_UNKNOWN_SOURCE",
            )

    def test_reject_incomplete_or_overlapping_count_proofs(self):
        with self.assertRaises(ValueError):
            classify([])
        with self.assertRaises(ValueError):
            classify([row(total=1, usable=1, nulls=1)])
        with self.assertRaises(ValueError):
            classify([row(total=1, usable=-1)])
        with self.assertRaises(ValueError):
            classify([row(total=True, usable=0)])

    def test_readonly_official_current_roster_and_exclusions(self):
        self.assertIn("official_current_listed listed", PRICE_QUALITY_SQL)
        self.assertIn("model_stock_exclusions", PRICE_QUALITY_SQL)
        self.assertIn("p.trade_date BETWEEN %(start)s AND %(end)s", PRICE_QUALITY_SQL)
        for forbidden in ("INSERT INTO", "UPDATE public.daily_prices",
                          "DELETE FROM", "TRUNCATE"):
            self.assertNotIn(forbidden, PRICE_QUALITY_SQL.upper())
