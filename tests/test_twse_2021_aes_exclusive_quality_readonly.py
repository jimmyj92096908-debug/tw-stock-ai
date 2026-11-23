"""Synthetic AES-only 2021 source-quality tests, zero Neon/owner file access."""
from decimal import Decimal
from datetime import date
import unittest

from tests.test_twse_2021_552_aes_neon_ohlcv_overlap_readonly import (
    AesNeonOverlapTests, prior_receipt,
)
from scripts.twse_2021_552_aes_neon_ohlcv_overlap_readonly import (
    evaluate as evaluate_overlap,
)
from scripts.twse_2021_aes_exclusive_quality_readonly import (
    evaluate, _check_previous, SCOPE,
)


class AesOnly2021QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        AesNeonOverlapTests.setUpClass()
        cls.roster = list(AesNeonOverlapTests.roster)
        cls.aes = dict(AesNeonOverlapTests.aes)
        cls.neon = [dict(r) for r in AesNeonOverlapTests.neon]
        for n in range(7):
            cls.neon[n]["price_change"] = None
        cls.union = prior_receipt()
        cls.receipt = evaluate_overlap(
            receipt=cls.union, roster=cls.roster,
            aes_rows=cls.aes, neon_rows=cls.neon,
        )
        assert cls.receipt["complete_economic_field_matches"] == 545

    def audit(self, **kwargs):
        return evaluate(
            union_receipt=kwargs.get("union", self.union),
            owner_parity_receipt=kwargs.get("prior", self.receipt),
            roster=kwargs.get("roster", self.roster),
            aes_rows=kwargs.get("aes", self.aes),
            neon_rows=kwargs.get("neon", self.neon),
        )

    def test_exact_aes_exclusive_quality_and_no_import_authority(self):
        r = self.audit()
        self.assertEqual(r["scope"], SCOPE)
        self.assertEqual(r["verified_original_aes_source_stockdate_keys"], 26120)
        self.assertEqual(r["verified_original_neon_overlap_keys"], 552)
        self.assertEqual(r["aes_exclusive_stockdate_source_keys"], 25568)
        self.assertEqual(r["aes_exclusive_source_keys_with_sane_core_ohlcv"], 25568)
        self.assertEqual(r["original_552_overlap_extended_economic_match_rows"], 545)
        self.assertEqual(r["original_552_neon_missing_price_change_rows"], 7)
        self.assertEqual(sum(r["aes_exclusive_source_keys_per_month"].values()), 25568)
        self.assertEqual(len(r["aes_exclusive_source_keys_per_day_aggregate"]), 28)
        self.assertTrue(r["original_552_overlap_critical_ohlcv_parity_revalidated"])
        self.assertFalse(r["production_backfill_approved"])
        self.assertFalse(r["historic_listing_and_trading_pit_eligibility_proven"])
        self.assertFalse(r["complete_neon_backups_and_restore_test_passed_here"])
        self.assertEqual(r["neon_writes"], 0)
        self.assertEqual(r["line_messages_sent"], 0)
        self.assertEqual(r["model_release"], "BLOCKED")
        self.assertNotIn("stock_id", str(r))

    def test_missing_optional_aes_fields_reported_not_faked(self):
        unique = next(k for k in self.aes if k not in {
            (r["trade_date"], r["stock_id"]) for r in self.neon
        })
        a = dict(self.aes)
        a[unique] = dict(a[unique], price_change=None, turnover=None)
        r = self.audit(aes=a)
        self.assertEqual(r["aes_exclusive_missing_optional_economic_field_counts"], {
            "price_change": 1, "turnover": 1
        })
        self.assertFalse(r["production_backfill_approved"])

    def test_missing_critical_or_bad_integer_never_pass(self):
        unique = next(k for k in self.aes if k not in {
            (r["trade_date"], r["stock_id"]) for r in self.neon
        })
        for field, value in (
            ("close", None),
            ("high", Decimal("50")),
            ("volume", "120000"),
            ("open", Decimal("0")),
            ("transactions", -1),
        ):
            a = dict(self.aes)
            a[unique] = dict(a[unique], **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.audit(aes=a)

    def test_changed_neon_price_or_seven_null_fields_fail_closed(self):
        neon = [dict(r) for r in self.neon]
        neon[0]["close"] = Decimal("101.2")
        with self.assertRaises(ValueError):
            self.audit(neon=neon)
        neon = [dict(r) for r in self.neon]
        neon[0]["price_change"] = Decimal("1")
        with self.assertRaises(ValueError):
            self.audit(neon=neon)

    def test_prior_receipt_tampering_and_duplicate_neon_fail(self):
        for field, value in (
            ("complete_economic_field_matches", 552),
            ("critical_ohlcv_field_matches", 551),
            ("model_release", "READY"),
            ("aes_exclusive_source_keys_never_written_to_neon", 25567),
        ):
            p = dict(self.receipt)
            p[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.audit(prior=p)
        neon = [dict(r) for r in self.neon]
        neon[0] = dict(neon[1])
        with self.assertRaises(ValueError):
            self.audit(neon=neon)


if __name__ == "__main__":
    unittest.main()
