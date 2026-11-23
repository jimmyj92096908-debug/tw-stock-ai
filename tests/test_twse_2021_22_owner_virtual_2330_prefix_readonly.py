"""Isolated research-only virtual AES+Neon 2330 source-prefix regression tests."""
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import secrets
import unittest

from scripts.twse_2021_28day_aes_current_cohort_density_readonly import EXPECTED_DAYS
from scripts.twse_2021_aes_exclusive_quality_readonly import SCOPE as QUALITY_SCOPE
from scripts.twse_2022_aes_neon_eligible_density_readonly import SCOPE as DENSITY_SCOPE
from scripts.twse_2021_22_owner_virtual_2330_prefix_readonly import (
    BULK, SECONDARY, SCOPE, NEON_SINGLE_ISSUER_SQL, BULK_DATES_SQL,
    stitch, validate_receipts, _stage, _failure_message,
    VirtualAuditStageError, run_owner, _authenticated_selected,
    _resolve_owner_vault_diagnosed,
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
            # Match actual producer's 2022 receipt, not the incorrect
            # neon_writes alias that caused the owner's guarded real audit
            # to fail after both source-tag changes.
            "schema_version": 1,
            "scope": DENSITY_SCOPE,
            "year": 2022,
            "official_current_listed_eligible_twse_issuers": 1092,
            "aes_prior_2022_source_calendar_dates": 162,
            "neon_original_bulk_source_calendar_dates": 84,
            "aes_source_days_overlap_neon_bulk_source_days": 0,
            "aes_plus_neon_unique_observed_source_dates": 246,
            "neon_bulk_date_set_matches_500_stock_density_date_set": True,
            "aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars": 246,
            "aes_neon_current_listed_stocks_with_all_246_source_dates": 825,
            "historical_adjusted_total_returns_approved": False,
            "model_release": "BLOCKED",
            "production_neon_writes": 0,
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

    def _run_1101(self, *, aes21=None, aes22=None, neon=None, cutoff=date(2022, 12, 30)):
        def rebind(rows):
            return [dict(r, stock_id="1101") for r in rows]
        return stitch(
            quality=self.quality,
            density=self.density,
            aes21=rebind(self.aes21) if aes21 is None else aes21,
            aes22=rebind(self.aes22) if aes22 is None else aes22,
            neon_rows=rebind(self.neon) if neon is None else neon,
            bulk_days=self.bulk_days,
            cutoff=cutoff,
            stock_id="1101",
        )

    def test_second_current_stock_1101_274_real_calendar_contract(self):
        # Synthetic stock bars with precisely the independently READ-ONLY
        # observed 1101 historical Neon bar calendar (28 + 246).
        result = self._run_1101()
        self.assertEqual(result["stock_id"], "1101")
        self.assertEqual(result["virtual_2021_22_combined_source_days"], 274)
        self.assertEqual(result["neon_AES_overlapping_stockdate_keys"], 190)
        self.assertEqual(result["neon_2022_market_bulk_calendar_days_with_stock_bar"], 84)
        self.assertEqual(result["neon_stock_official_price_source_tags"], {SECONDARY: 274})
        self.assertTrue(result["neon_AES_overlap_OHLCV_exact"])
        self.assertEqual(result["as_of_last_240_observed_source_days"], 240)
        self.assertNotIn("neon_AES_overlapping_2330_source_stockdate_keys", result)
        self.assertNotIn("neon_2330_official_price_source_tags", result)
        self.assertFalse(result["historical_adjusted_total_returns_approved"]
                         if "historical_adjusted_total_returns_approved" in result
                         else result["corporate_action_and_publication_vintage_verified"])
        self.assertFalse(result["raw_unadjusted_sma240_is_tradable_signal"])
        self.assertFalse(result["production_backfill_approved"])
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["model_release"], "BLOCKED")

    def test_second_stock_1101_price_conflict_fails_with_own_diagnostic(self):
        changed = [dict(row, stock_id="1101") for row in self.neon]
        changed[0] = dict(changed[0], close=Decimal("104.50"))
        with self.assertRaises(VirtualAuditStageError) as ctx:
            self._run_1101(neon=changed)
        self.assertEqual(ctx.exception.code, "AES_NEON_1101_CORE_OHLCV")
        self.assertNotIn("104.50", str(ctx.exception))

    def test_second_stock_1101_rejects_foreign_issuer_or_missing_dates(self):
        foreign_neon = [dict(row, stock_id="1101") for row in self.neon]
        foreign_neon[0] = dict(foreign_neon[0], stock_id="2330")
        with self.assertRaises(ValueError):
            self._run_1101(neon=foreign_neon)
        missing = [dict(row, stock_id="1101") for row in self.neon
                   if row["trade_date"] != self.bulk_days[0]]
        with self.assertRaises(VirtualAuditStageError) as ctx:
            self._run_1101(neon=missing)
        self.assertEqual(ctx.exception.code, "SOURCE_2022_CALENDAR")
        for outside in ("1589", "1301", "2317", "2454", "2882"):
            with self.subTest(outside=outside), self.assertRaises(ValueError):
                stitch(
                    quality=self.quality, density=self.density,
                    aes21=self.aes21, aes22=self.aes22,
                    neon_rows=self.neon, bulk_days=self.bulk_days,
                    cutoff=date(2022, 12, 30), stock_id=outside)

    def test_second_stock_1101_lookahead_mutation_invariant(self):
        earlier = self._run_1101(cutoff=date(2022, 12, 29))
        future = [dict(row, stock_id="1101") for row in self.neon]
        idx = next(i for i, row in enumerate(future)
                   if row["trade_date"] == date(2022, 12, 30))
        future[idx] = dict(future[idx], close=Decimal("133.25"))
        res = self._run_1101(neon=future, cutoff=date(2022, 12, 29))
        self.assertEqual(
            earlier["as_of_raw_prefix_sha256_private"],
            res["as_of_raw_prefix_sha256_private"])
        self.assertEqual(
            earlier["as_of_raw_unadjusted_sma240_private_research_value"],
            res["as_of_raw_unadjusted_sma240_private_research_value"])
        self.assertEqual(res["source_rows_after_asof_used_in_computation"], 0)

    def test_second_stock_1101_real_encrypted_synthetic_replay_filters_rows(self):
        from scripts.twse_local_encrypted_archive import encrypt_rows
        key = secrets.token_hex(32)
        d1, d2 = date(2022, 1, 3), date(2022, 1, 4)
        with TemporaryDirectory() as directory:
            p = Path(directory) / "two-stocks-2022.twseenc"
            rows = [
                dict(source_bar(d, close="101.25"), stock_id=sid,
                     retrieved_at=datetime(2026, 11, 20, tzinfo=timezone.utc))
                for d in (d1, d2)
                for sid in ("1101", "2330")
            ]
            encrypt_rows(rows, p, start=d1, end=d2, hex_key=key)
            first = _authenticated_selected([p], key, 2022, 2, stock_id="1101")
            second = _authenticated_selected([p], key, 2022, 2, stock_id="2330")
            self.assertEqual([row["trade_date"] for row in first], [d1, d2])
            self.assertEqual([row["trade_date"] for row in second], [d1, d2])
            self.assertEqual({row["stock_id"] for row in first}, {"1101"})
            self.assertEqual({row["stock_id"] for row in second}, {"2330"})

    def test_owner_run_rejects_unlisted_stock_before_any_private_io(self):
        from unittest.mock import patch
        module = "scripts.twse_2021_22_owner_virtual_2330_prefix_readonly"
        with patch(module + "._private_archives") as archives:
            with self.assertRaises(VirtualAuditStageError):
                run_owner(
                    archive21="unused", archive22="unused", vault="unused",
                    quality_path="unused", density_path="unused",
                    out="unused", cutoff=date(2022, 12, 30),
                    url="unused", stock_id="1589")
        archives.assert_not_called()

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

    def test_vault_diagnostics_reject_conflicting_env_key_without_prompt(self):
        import os
        from unittest.mock import patch
        module = "scripts.twse_2021_22_owner_virtual_2330_prefix_readonly"
        with patch.dict(os.environ, {"STOCK_ARCHIVE_KEY_HEX": "not-printed-hex"}):
            with patch(module + "._hidden_vault_prompt") as prompt:
                with self.assertRaises(VirtualAuditStageError) as failure:
                    _resolve_owner_vault_diagnosed("not-a-real-file")
                prompt.assert_not_called()
        self.assertEqual(failure.exception.code, "AES_KEY_VAULT_MODE_CONFLICT")
        self.assertNotIn("not-printed-hex", str(failure.exception))

    def test_vault_diagnostics_file_prompt_and_password_are_private(self):
        import os
        from unittest.mock import patch
        module = "scripts.twse_2021_22_owner_virtual_2330_prefix_readonly"
        with patch.dict(os.environ, {"STOCK_ARCHIVE_KEY_HEX": ""}):
            with patch(module + "._existing_private_vault",
                       side_effect=ValueError("C:/owner-secret-key-path")):
                with self.assertRaises(VirtualAuditStageError) as failure:
                    _resolve_owner_vault_diagnosed("private-vault")
            self.assertEqual(failure.exception.code, "AES_KEY_VAULT_PATH")
            self.assertNotIn("C:/owner-secret", str(failure.exception))
            with patch(module + "._existing_private_vault", return_value=Path("private.twsekey")):
                with patch(module + "._hidden_vault_prompt",
                           side_effect=ValueError("desktop-cancelled-with-owner-path")):
                    with self.assertRaises(VirtualAuditStageError) as failure:
                        _resolve_owner_vault_diagnosed("private-vault")
                self.assertEqual(failure.exception.code, "AES_KEY_VAULT_PROMPT")
                with patch(module + "._hidden_vault_prompt",
                           return_value="do-not-print-my-private-passphrase"):
                    with patch(module + ".load_archive_key_hex",
                               side_effect=ValueError("vault ciphertext or password invalid")):
                        with self.assertRaises(VirtualAuditStageError) as failure:
                            _resolve_owner_vault_diagnosed("private-vault")
                self.assertEqual(failure.exception.code, "AES_KEY_VAULT_DECRYPT")
                self.assertNotIn("do-not-print", str(failure.exception))
                for code in ("AES_KEY_VAULT_PATH", "AES_KEY_VAULT_PROMPT",
                             "AES_KEY_VAULT_DECRYPT", "AES_KEY_VAULT_MODE_CONFLICT"):
                    self.assertIn("diagnostic_stage=" + code, _failure_message(code))

    def test_vault_diagnostics_accepts_real_synthetic_encrypted_vault(self):
        import os
        from unittest.mock import patch
        from scripts.twse_archive_key_vault import initialize_vault
        phrase = "an original private synthetic test passphrase 0123456789"
        with TemporaryDirectory() as base:
            first = Path(base) / "first"
            second = Path(base) / "second"
            first.mkdir()
            second.mkdir()
            vault = first / "synthetic.twsekey"
            recovery = second / "synthetic.twsekey"
            receipt = initialize_vault(
                vault_path=vault, recovery_path=recovery, passphrase=phrase)
            self.assertTrue(receipt["two_identical_private_encrypted_copies_verified"])
            module = "scripts.twse_2021_22_owner_virtual_2330_prefix_readonly"
            with patch.dict(os.environ, {"STOCK_ARCHIVE_KEY_HEX": ""}):
                with patch(module + "._hidden_vault_prompt", return_value=phrase):
                    secret = _resolve_owner_vault_diagnosed(vault)
            self.assertEqual(len(secret), 64)
            self.assertNotIn(secret, vault.read_text())
            self.assertNotIn(phrase, vault.read_text())
            self.assertNotIn(secret, _failure_message("AES_KEY_VAULT_DECRYPT"))

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

    def test_2022_real_report_schema_rejected_if_write_guard_missing_or_changed(self):
        # Importing the actual 2022 density receipt has no neon_writes key.
        # That is not evidence of writes: the canonical producer field is
        # production_neon_writes, which must be zero.
        q, d = qualified_receipts()
        self.assertNotIn("neon_writes", d)
        self.assertEqual(d["production_neon_writes"], 0)
        validate_receipts(q, d)
        result = self.run_stitch(quality=q, density=d)
        self.assertEqual(result["virtual_2021_22_combined_source_days"], 274)

        for mutation in (
            {"production_neon_writes": 1},
            {"production_neon_writes": None},
            {"production_neon_writes": True},
            {"schema_version": 2},
            {"year": 2021},
            {"aes_source_days_overlap_neon_bulk_source_days": 1},
            {"aes_plus_neon_unique_observed_source_dates": 245},
            {"neon_bulk_date_set_matches_500_stock_density_date_set": False},
            {"historical_adjusted_total_returns_approved": True},
        ):
            bad = dict(d, **mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_receipts(q, bad)

        absent = dict(d)
        absent.pop("production_neon_writes")
        absent["neon_writes"] = 0  # old broken alias must never bypass guard
        with self.assertRaises(ValueError):
            validate_receipts(q, absent)

    def test_real_density_receipt_producer_uses_production_neon_writes(self):
        # Source-contract regression: ensure the protected importer agrees
        # with the producer's declared output schema.
        import inspect
        from scripts.twse_2022_aes_neon_eligible_density_readonly import (
            evaluate as evaluate_2022_density,
        )
        source = inspect.getsource(evaluate_2022_density)
        self.assertIn('"production_neon_writes":0', source)
        self.assertNotIn('"neon_writes":0', source)

    def test_real_encrypted_2022_replay_skips_authentic_off_year_files(self):
        # The real 2022 AES source auditor accepts a shared private folder:
        # it AUTHENTICATES extra-year files, then filters to original 2022.
        # Previous 2330 code instead rejected any 2023 source record during
        # replay despite the successful prior 162-day owner report.
        from scripts.twse_local_encrypted_archive import encrypt_rows
        key = secrets.token_hex(32)
        with TemporaryDirectory() as directory:
            first = date(2022, 1, 3)
            second = date(2022, 1, 4)
            later = date(2023, 1, 3)
            p22 = Path(directory) / "original-2022.twseenc"
            p23 = Path(directory) / "other-year-2023.twseenc"

            def archived(day, sid="2330"):
                return dict(
                    source_bar(day),
                    stock_id=sid,
                    retrieved_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
                )

            encrypt_rows(
                [archived(first), archived(second)], p22,
                start=first, end=second, hex_key=key,
            )
            encrypt_rows(
                [archived(later)], p23,
                start=later, end=later, hex_key=key,
            )
            # Intentionally supply the next-year file FIRST, as globs can.
            result = _authenticated_selected([p23, p22], key, 2022, 2)
            self.assertEqual([row["trade_date"] for row in result], [first, second])
            self.assertTrue(all(row["stock_id"] == "2330" for row in result))

            # Skipping is NOT trusting: corrupt skipped-year AES ciphertext
            # must still fail, even though it is outside the 2022 window.
            raw = p23.read_bytes()
            p23.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0x01]))
            with self.assertRaises(Exception):
                _authenticated_selected([p23, p22], key, 2022, 2)

    def test_2022_replay_rejects_missing_2330_and_cross_year_archives(self):
        from scripts.twse_local_encrypted_archive import encrypt_rows
        key = secrets.token_hex(32)
        with TemporaryDirectory() as directory:
            day1, day2 = date(2022, 1, 3), date(2022, 1, 4)
            p = Path(directory) / "missing-stock.twseenc"
            def bar(day, sid):
                return dict(
                    source_bar(day),
                    stock_id=sid,
                    retrieved_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
                )
            encrypt_rows(
                [bar(day1, "2330"), bar(day2, "1101")], p,
                start=day1, end=day2, hex_key=key,
            )
            with self.assertRaises(ValueError):
                _authenticated_selected([p], key, 2022, 2)

            cross = Path(directory) / "cross-year-unsupported.twseenc"
            a, b = date(2022, 12, 30), date(2023, 1, 2)
            encrypt_rows(
                [bar(a, "2330"), bar(b, "2330")], cross,
                start=a, end=b, hex_key=key,
            )
            with self.assertRaises(ValueError):
                _authenticated_selected([cross], key, 2022, 1)

    def test_live_sql_is_read_only_and_bounded(self):
        self.assertIn("stock_id=%s", NEON_SINGLE_ISSUER_SQL)
        self.assertIn("LIMIT 321", NEON_SINGLE_ISSUER_SQL)
        self.assertIn("LIMIT 100", BULK_DATES_SQL)
        for sql in (NEON_SINGLE_ISSUER_SQL,BULK_DATES_SQL):
            for op in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE "):
                self.assertNotIn(op, sql.upper())


if __name__ == "__main__":
    unittest.main()
