"""Isolated research-only virtual AES+Neon 2330 source-prefix regression tests."""
from datetime import date, timedelta
from decimal import Decimal
import unittest

from scripts.twse_2021_28day_aes_current_cohort_density_readonly import EXPECTED_DAYS
from scripts.twse_2021_aes_exclusive_quality_readonly import SCOPE as QUALITY_SCOPE
from scripts.twse_2022_aes_neon_eligible_density_readonly import SCOPE as DENSITY_SCOPE
from scripts.twse_2021_22_owner_virtual_2330_prefix_readonly import (
    BULK, SECONDARY, SCOPE, NEON_SINGLE_ISSUER_SQL, BULK_DATES_SQL,
    stitch, validate_receipts, _stage, _failure_message,
    VirtualAuditStageError, run_owner,
)


def source_bar(day, *, neon=False, src=BULK, close="101.25"):
    c = Decimal(close)
    return {
        "market": "twse", "stock_id": "2330", "trade_date": day,
        "source": src if neon else BULK,
        "open": c - Decimal("1"), "high": c + Decimal("2"),
        "low": c - Decimal("2"), "close": c,
        "volume": 800000, "turnover": Decimal("81000000.000"),
        "price_change": Decimal("1.0"), "transactions": 200,
    }


def qualified_receipts():
    return (
        {
            "scope": QUALITY_SCOPE,
            "verified_original_aes_source_stockdate_keys": 26120,
            "verified_original_neon_overlap_keys": 552,
            "original_552_overlap_critical_ohlcv_parity_revalidated": True,
            "aes_exclusive_stockdate_source_keys": 25568,
            "aes_exclusive_source_keys_with_sane_core_ohlcv": 25568,
            "aes_exclusive_distinct_current_survivor_issuers": 919,
            "aes_exclusive_missing_optional_economic_field_counts": {},
            "production_backfill_approved": False,
            "model_release": "BLOCKED", "neon_writes": 0,
            "line_messages_sent": 0,
        },
        {
            "scope": DENSITY_SCOPE,
            "aes_prior_2022_source_calendar_dates": 162,
            "neon_original_bulk_source_calendar_dates": 84,
            "aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars": 246,
            "aes_neon_current_listed_stocks_with_all_246_source_dates": 825,
            "model_release": "BLOCKED", "neon_writes": 0,
            "line_messages_sent": 0,
        },
    )


class Virtual2330Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = date(2022, 1, 3)
        weekdays = []
        while d <= date(2022, 12, 30):
            if d.weekday() < 5:
                weekdays.append(d)
            d += timedelta(days=1)
        assert len(weekdays) == 260
        calendar = weekdays[:244] + weekdays[-2:]
        assert len(calendar) == 246 and calendar[-2] == date(2022, 12, 29)
        q, density = qualified_receipts()
        cls.quality = q
        cls.density = density
        cls.aes21 = [source_bar(d) for d in sorted(EXPECTED_DAYS)]
        cls.aes22 = [source_bar(d) for d in calendar[:162]]
        cls.bulk_days = calendar[162:]
        # Real Neon READ ONLY snapshot, 2026-11-23: all 274 valid 2330
        # price rows are TWSE_STOCK_DAY, including all 84 dates whose
        # *market-wide* calendar was established by other BULK-source stocks.
        cls.neon = [
            source_bar(d, neon=True, src=SECONDARY)
            for d in sorted(EXPECTED_DAYS) + calendar
        ]
        assert len(cls.neon) == 274

    def run_stitch(self, **kw):
        return stitch(
            quality=kw.get("quality", self.quality),
            density=kw.get("density", self.density),
            aes21=kw.get("aes21", self.aes21),
            aes22=kw.get("aes22", self.aes22),
            neon_rows=kw.get("neon", self.neon),
            bulk_days=kw.get("bulk", self.bulk_days),
            cutoff=kw.get("cutoff", date(2022, 12, 30)),
        )

    def test_exact_274_day_virtual_research_not_live_model(self):
        r = self.run_stitch()
        self.assertEqual(r["scope"], SCOPE)
        self.assertEqual(r["virtual_2021_22_combined_source_days"], 274)
        self.assertEqual(r["virtual_2022_source_calendar_days"], 246)
        self.assertEqual(r["as_of_raw_prefix_source_days"], 274)
        self.assertEqual(r["neon_AES_overlapping_2330_source_stockdate_keys"], 190)
        self.assertEqual(r["neon_2022_market_bulk_calendar_days_with_2330_bar"], 84)
        self.assertEqual(r["neon_2330_official_price_source_tags"], {SECONDARY: 274})
        self.assertEqual(r["as_of_last_240_observed_source_days"], 240)
        self.assertEqual(r["as_of_raw_unadjusted_sma240_private_research_value"], "101.25")
        self.assertTrue(r["neon_AES_overlap_OHLCV_exact"])
        self.assertEqual(r["neon_writes"], 0)
        self.assertEqual(r["line_messages_sent"], 0)
        self.assertFalse(r["all_five_year_market_data_complete"])
        self.assertFalse(r["corporate_action_and_publication_vintage_verified"])
        self.assertFalse(r["production_backfill_approved"])
        self.assertFalse(r["raw_unadjusted_sma240_is_tradable_signal"])
        self.assertEqual(r["model_release"], "BLOCKED")

    def test_asof_prefix_does_not_leak_future_last_date(self):
        earlier = self.run_stitch(cutoff=date(2022, 12, 29))
        a = [dict(x) for x in self.neon]
        target = next(i for i, x in enumerate(a)
                      if x["trade_date"] == date(2022,12,30))
        a[target] = source_bar(date(2022,12,30), neon=True,close="130.0")
        earlier_with_future_mutated = self.run_stitch(
            cutoff=date(2022,12,29), neon=a)
        self.assertEqual(earlier["as_of_raw_unadjusted_sma240_private_research_value"],
                         earlier_with_future_mutated["as_of_raw_unadjusted_sma240_private_research_value"])
        self.assertEqual(earlier["as_of_raw_prefix_sha256_private"],
                         earlier_with_future_mutated["as_of_raw_prefix_sha256_private"])
        self.assertEqual(earlier["as_of_raw_prefix_source_days"], 273)
        self.assertEqual(earlier["source_rows_after_asof_used_in_computation"], 0)
        later = self.run_stitch(neon=a)
        self.assertNotEqual(later["as_of_raw_prefix_sha256_private"],
                            self.run_stitch()["as_of_raw_prefix_sha256_private"])

    def test_close_conflict_fails_instead_of_preferring_a_source(self):
        a = [dict(x) for x in self.neon]
        a[0] = source_bar(a[0]["trade_date"], neon=True, src=SECONDARY,close="103.0")
        with self.assertRaises(ValueError):
            self.run_stitch(neon=a)

    def test_optional_null_is_not_claimed_complete(self):
        a = [dict(x) for x in self.neon]
        a[0]["price_change"] = None
        result = self.run_stitch(neon=a)
        self.assertEqual(result["neon_AES_optional_field_discrepancies"], {
            "unverifiable_price_change": 1
        })

    def test_missing_bulk_day_never_reconstructs_synthetic_price(self):
        a = [dict(x) for x in self.neon if x["trade_date"] != self.bulk_days[0]]
        with self.assertRaises(ValueError):
            self.run_stitch(neon=a)

    def test_market_bulk_calendar_can_have_stock_day_provenance(self):
        # Both official row sources are allowed on a verified market BULK
        # date. Other dates cannot silently turn into fabricated bulk days.
        a = [dict(x) for x in self.neon]
        target = next(i for i, r in enumerate(a)
                      if r["trade_date"] == self.bulk_days[0])
        a[target]["source"] = BULK
        report = self.run_stitch(neon=a)
        self.assertEqual(report["neon_2022_market_bulk_calendar_days_with_2330_bar"], 84)
        self.assertEqual(report["neon_2330_official_price_source_tags"], {
            BULK: 1, SECONDARY: 273
        })

    def test_bulk_tag_outside_bulk_date_is_rejected(self):
        a = [dict(x) for x in self.neon]
        target = next(i for i, r in enumerate(a)
                      if r["trade_date"] == self.aes22[0]["trade_date"])
        a[target]["source"] = BULK
        with self.assertRaises(ValueError):
            self.run_stitch(neon=a)

    def test_neon_only_unverified_date_is_rejected(self):
        a = [dict(x) for x in self.neon]
        day_outside_246 = date(2022, 12, 28)  # synthetic calendar omits this
        self.assertNotIn(day_outside_246, self.bulk_days)
        self.assertNotIn(day_outside_246, [r["trade_date"] for r in self.aes22])
        a.append(source_bar(day_outside_246, neon=True, src=SECONDARY))
        with self.assertRaises(ValueError):
            self.run_stitch(neon=a)

    def test_duplicate_neon_and_tampered_prior_receipts_fail(self):
        a = list(self.neon) + [dict(self.neon[0])]
        with self.assertRaises(ValueError):
            self.run_stitch(neon=a)
        q = dict(self.quality, production_backfill_approved=True)
        with self.assertRaises(ValueError):
            self.run_stitch(quality=q)
        p = dict(self.density, aes_prior_2022_source_calendar_dates=161)
        with self.assertRaises(ValueError):
            self.run_stitch(density=p)

    def test_invalid_source_price_or_1589_or_time_window_fails(self):
        a = [dict(x) for x in self.aes22]
        a[0] = dict(a[0], high=Decimal("20"))
        with self.assertRaises(ValueError):
            self.run_stitch(aes22=a)
        a = [dict(x) for x in self.aes22]
        a[0] = dict(a[0], stock_id="1589")
        with self.assertRaises(ValueError):
            self.run_stitch(aes22=a)
        with self.assertRaises(ValueError):
            self.run_stitch(cutoff=date(2023,1,3))
        a = [dict(x) for x in self.neon]
        a[0] = dict(a[0], trade_date=date(2023,1,3))
        with self.assertRaises(ValueError):
            self.run_stitch(neon=a)

    def test_private_failure_stage_allowlist_never_exposes_raw_error(self):
        secret = "postgresql://owner-secret:password@neon/private-price"
        def bad_external_call():
            raise ValueError(secret)
        with self.assertRaises(VirtualAuditStageError) as ctx:
            _stage("NEON_READONLY_SNAPSHOT", bad_external_call)
        self.assertEqual(ctx.exception.code, "NEON_READONLY_SNAPSHOT")
        self.assertEqual(str(ctx.exception), "NEON_READONLY_SNAPSHOT")
        text = _failure_message(ctx.exception.code)
        self.assertIn("diagnostic_stage=NEON_READONLY_SNAPSHOT", text)
        self.assertNotIn(secret, text)
        self.assertNotIn(secret, str(ctx.exception))
        self.assertEqual(_failure_message(secret).count(secret), 0)
        self.assertIn("diagnostic_stage=UNCLASSIFIED", _failure_message(secret))

    def test_archive_layout_stage_fails_before_any_private_neon_read(self):
        from unittest.mock import patch
        module = "scripts.twse_2021_22_owner_virtual_2330_prefix_readonly"
        with patch(module + "._private_archives",
                   side_effect=ValueError("C:/secret-owner-path")), \
             patch(module + ".capture_neon") as read_neon:
            with self.assertRaises(VirtualAuditStageError) as ctx:
                run_owner(
                    archive21="nonexistent", archive22="nonexistent",
                    vault="unused", quality_path="unused", density_path="unused",
                    out="unused", cutoff=date(2022,12,30), url="unused")
        self.assertEqual(ctx.exception.code, "ARCHIVE_PATHS")
        self.assertNotIn("secret", str(ctx.exception))
        read_neon.assert_not_called()

    def test_core_mismatch_and_calendar_missing_have_distinct_safe_codes(self):
        changed = [dict(x) for x in self.neon]
        changed[0] = source_bar(
            changed[0]["trade_date"], neon=True, src=SECONDARY, close="104.50")
        with self.assertRaises(VirtualAuditStageError) as ctx:
            self.run_stitch(neon=changed)
        self.assertEqual(ctx.exception.code, "AES_NEON_2330_CORE_OHLCV")
        self.assertNotIn("104.50", str(ctx.exception))

        missing = [dict(x) for x in self.neon
                   if x["trade_date"] != self.bulk_days[0]]
        with self.assertRaises(VirtualAuditStageError) as ctx:
            self.run_stitch(neon=missing)
        self.assertEqual(ctx.exception.code, "SOURCE_2022_CALENDAR")

    def test_live_sql_is_read_only_and_bounded(self):
        self.assertIn("stock_id=%s", NEON_SINGLE_ISSUER_SQL)
        self.assertIn("LIMIT 321", NEON_SINGLE_ISSUER_SQL)
        self.assertIn("LIMIT 100", BULK_DATES_SQL)
        for sql in (NEON_SINGLE_ISSUER_SQL,BULK_DATES_SQL):
            for op in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE "):
                self.assertNotIn(op, sql.upper())


if __name__ == "__main__":
    unittest.main()
