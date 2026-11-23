"""Synthetic read-only 2021 AES / Neon economic parity regression suite."""
import unittest
from datetime import date
from decimal import Decimal

from scripts.twse_2021_28day_aes_current_cohort_density_readonly import EXPECTED_DAYS
from scripts.twse_2021_552_aes_neon_ohlcv_overlap_readonly import (
    READONLY_SQL, SCOPE, compare_economic, evaluate,
)
from scripts.twse_2021_28day_aes_neon_stockdate_union_readonly import SCOPE as UNION_SCOPE


def sample_row(d, s, source="TWSE_MI_INDEX_ALLBUT0999"):
    return dict(
        trade_date=d, stock_id=s, market="twse", source=source,
        open=Decimal("100.0000"), high=Decimal("103.50"),
        low=Decimal("99.25"), close=Decimal("101.0000"),
        volume=120000, turnover=Decimal("12120000.000"),
        price_change=Decimal("1.0"), transactions=400,
    )


def prior_receipt():
    return {
        "schema_version": 1, "scope": UNION_SCOPE,
        "authenticated_owner_2021_source_dates": 28,
        "prior_2021_aes_source_stock_date_pairs": 26120,
        "prior_2021_neon_source_stock_date_pairs": 552,
        "aes_neon_overlapping_source_stock_date_pairs": 552,
        "aes_exclusive_source_stock_date_pairs": 25568,
        "neon_exclusive_source_stock_date_pairs": 0,
        "actual_deduplicated_aes_neon_stock_date_pairs": 26120,
        "current_stocks_with_no_source_day_in_2021": 153,
        "production_neon_writes": 0,
        "line_messages_sent": 0, "model_release": "BLOCKED",
    }


class AesNeonOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        roster = [f"{n:04d}" for n in range(1000, 2093) if n != 1589]
        assert len(roster) == 1092
        days = sorted(EXPECTED_DAYS)
        assert len(days) == 28
        aes = {}
        first = roster[:900]
        extra = roster[900:939]
        for d in days:
            for sid in first:
                aes[(d, sid)] = sample_row(d, sid)
        for i, sid in enumerate(extra):
            num = 26 if i < 16 else 22 if i < 37 else 21
            for d in days[:num]:
                aes[(d, sid)] = sample_row(d, sid)
        assert len(aes) == 26120
        neon = []
        for j, d in enumerate(days):
            for sid in first[:20 if j < 20 else 19]:
                neon.append(sample_row(d, sid, source="TWSE_STOCK_DAY"))
        assert len(neon) == 552
        cls.roster = roster
        cls.aes = aes
        cls.neon = neon

    def test_exact_552_overlap_without_assuming_ready_for_import(self):
        report = evaluate(
            receipt=prior_receipt(), roster=self.roster,
            aes_rows=self.aes, neon_rows=self.neon,
        )
        self.assertEqual(report["scope"], SCOPE)
        self.assertEqual(report["exact_source_key_overlap"], 552)
        self.assertEqual(report["aes_exclusive_source_keys_never_written_to_neon"], 25568)
        self.assertEqual(report["complete_economic_field_matches"], 552)
        self.assertEqual(report["critical_ohlcv_field_matches"], 552)
        self.assertTrue(report["all_552_critical_ohlcv_parity_verified"])
        self.assertFalse(report["aes_exclusive_price_rows_approved_for_import"])
        self.assertFalse(report["safe_to_write_production_history"])
        self.assertEqual(report["neon_writes"], 0)
        self.assertEqual(report["line_messages_sent"], 0)
        self.assertEqual(report["model_release"], "BLOCKED")

    def test_price_conflict_and_missing_field_never_silently_match(self):
        rows = [dict(x) for x in self.neon]
        rows[0]["close"] = Decimal("101.20")
        for r in rows[1:8]:
            r["price_change"] = None
        result = evaluate(
            receipt=prior_receipt(), roster=self.roster,
            aes_rows=self.aes, neon_rows=rows,
        )
        self.assertEqual(result["critical_ohlcv_field_matches"], 551)
        self.assertEqual(result["complete_economic_field_matches"], 544)
        self.assertEqual(result["per_field_different_or_unverifiable_counts"], {
            "different_close": 1, "unverifiable_price_change": 7,
        })
        self.assertFalse(result["all_552_critical_ohlcv_parity_verified"])
        self.assertFalse(result["all_552_extended_economic_parity_verified"])
        self.assertTrue(result["private_552_overlap_exceptions_without_prices"])
        self.assertNotIn("101.20", str(result["private_552_overlap_exceptions_without_prices"]))

    def test_missing_close_is_unverifiable_not_zero_or_equal(self):
        a = sample_row(date(2021, 11, 23), "2330")
        b = dict(a, close=None)
        changed, missing = compare_economic(a, b)
        self.assertEqual(changed, ())
        self.assertEqual(missing, ("close",))
        b["close"] = Decimal("0")
        changed, missing = compare_economic(a, b)
        self.assertEqual(changed, ("close",))
        self.assertEqual(missing, ())

    def test_duplicate_foreign_and_nonoverlap_keys_fail_closed(self):
        scenarios = []
        a = [dict(x) for x in self.neon]
        a[0] = dict(a[1])
        scenarios.append(a)
        a = [dict(x) for x in self.neon]
        a[0]["stock_id"] = "1589"
        scenarios.append(a)
        a = [dict(x) for x in self.neon]
        a[0]["stock_id"] = self.roster[-1]
        scenarios.append(a)
        a = [dict(x) for x in self.neon]
        a[0]["source"] = "UNKNOWN"
        scenarios.append(a)
        for rows in scenarios:
            with self.subTest(row=rows[0]["stock_id"]), self.assertRaises(ValueError):
                evaluate(receipt=prior_receipt(), roster=self.roster,
                         aes_rows=self.aes, neon_rows=rows)

    def test_unverified_receipt_and_economics_fail_closed(self):
        bad = prior_receipt()
        bad["neon_exclusive_source_stock_date_pairs"] = 1
        with self.assertRaises(ValueError):
            evaluate(receipt=bad, roster=self.roster,
                     aes_rows=self.aes, neon_rows=self.neon)
        a = dict(self.aes)
        first = next(iter(a))
        a[first] = dict(a[first], volume="120000")
        with self.assertRaises(ValueError):
            evaluate(receipt=prior_receipt(), roster=self.roster,
                     aes_rows=a, neon_rows=self.neon)

    def test_live_query_is_bounded_and_research_only(self):
        self.assertIn("official_current_listed", READONLY_SQL)
        self.assertIn("model_stock_exclusions", READONLY_SQL)
        self.assertIn("p.stock_id<>'1589'", READONLY_SQL)
        self.assertIn("p.close>0", READONLY_SQL)
        self.assertIn("LIMIT 801", READONLY_SQL)
        for banned in ("INSERT INTO ", "DELETE FROM ", "UPDATE ", "TRUNCATE ", "DROP TABLE "):
            self.assertNotIn(banned, READONLY_SQL.upper())


if __name__ == "__main__":
    unittest.main()
