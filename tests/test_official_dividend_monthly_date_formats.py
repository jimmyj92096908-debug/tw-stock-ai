"""Offline tests for real TWSE/TPEx ROC vs Gregorian dates in official event previews."""
from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from scripts import official_dividend_monthly_preview as preview

CAPTURE = datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc)
ROSTER = {("twse", str(1000+i)) for i in range(800)} | {
    ("tpex", str(2000+i)) for i in range(800)
}


def candidate(stock, day):
    return {
        "證券代號": stock, "除權息日期": day, "權或息": "息",
        "除權息前收盤價": "100", "除權息參考價": "98",
        "現金股利": "2",
    }


def feeds(dates):
    return {
        ("twse", "ex", preview.TWSE_EX_URL):
            [candidate("1234", x) for x in dates],
        ("twse", "reduction", preview.TWSE_REDUCTION_URL): [],
        ("tpex", "ex", preview.TPEX_EX_URL): [],
        ("tpex", "reduction", preview.TPEX_REDUCTION_URL): [],
    }


class OfficialDividendsDateTests(unittest.TestCase):
    def test_gregorian_and_roc_compact_and_separated(self):
        values = (
            "1150819", "20260819", "115/08/19", "2026/08/19",
            "115年08月19日", "2026-8-19", "115.8.19",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    preview._parse_official_event_date(
                        value, market="twse", kind="ex", symbol="1234"),
                    date(2026, 8, 19),
                )

    def test_previous_year_roc_compact_date_not_misparsed_as_3051(self):
        old = preview._parse_official_event_date(
            "1140815", market="twse", kind="ex", symbol="1234")
        self.assertEqual(old, date(2025, 8, 15))

    def test_partial_bad_month_bad_day_and_year_are_rejected(self):
        for raw in (
            "115/13/19", "115/00/19", "115/02/30", "115/08",
            "202608", "115082", "2026080112", "321/08/19", "abc",
        ):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "official|event"):
                    preview._parse_official_event_date(
                        raw, market="twse", kind="ex", symbol="1234")

    def test_date_error_mentions_source_kind_stock_and_raw_date(self):
        with self.assertRaisesRegex(
            ValueError, "twse/ex.*1234.*'202608'"):
            preview._parse_official_event_date(
                "202608", market="twse", kind="ex", symbol="1234")

    def test_legacy_tpex_roc_date_and_outside_period_counts(self):
        g = feeds(["1150819", "1140815"])
        result = preview.assess(g,
            start=date(2026, 8, 1), end=date(2026, 8, 31),
            observed_at=CAPTURE, current_stocks=ROSTER, existing_counts=[])
        self.assertEqual(result["raw_four_digit_source_events"], 1)
        self.assertEqual(result["distinct_candidate_economic_events"], 1)
        self.assertEqual(result["candidates"][0]["ex_date"], "2026-08-19")
        src = next(x for x in result["source_evidence"]
                   if x["market"] == "twse" and x["kind"] == "ex")
        self.assertEqual(src["excluded_outside_requested_date_range"], 1)

    def test_malformed_in_range_looking_date_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "twse/ex"):
            preview.assess(feeds(["115/13/19"]),
                start=date(2026, 8, 1), end=date(2026, 8, 31),
                observed_at=CAPTURE, current_stocks=ROSTER, existing_counts=[])


if __name__ == "__main__":
    unittest.main()
