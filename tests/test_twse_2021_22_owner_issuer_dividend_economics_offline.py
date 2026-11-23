"""Synthetic and source-grounded offline 1101/2330 dividend-economics tests.

No actual owner AES data, Neon credentials, raw stock prices, LINE or live web.
"""
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from scripts import twse_2021_22_owner_issuer_dividend_economics_offline as m
from scripts import twse_2021_22_owner_two_stock_action_gap_readonly as gap
from tests import test_twse_2021_22_owner_two_stock_action_gap_readonly as prior_fixture


def accepted_gap():
    # The exact previously-tested synthetic action-gap output contract,
    # NOT an invented claim that a real owner private report was seen by CI.
    return gap.evaluate(
        prior=prior_fixture.original(),
        actions=[],
        density=prior_fixture.density(),
        event_days=prior_fixture.real_event_days(),
    )


class IssuerDividendEconomicsOfflineTests(TestCase):
    def test_issuer_facts_are_exactly_six_stated_cash_and_stock_values(self):
        report = m.evaluate(accepted_gap())
        self.assertEqual(report["scope"], m.SCOPE)
        self.assertEqual(report["reviewed_issuer_retrospective_event_rows"], 6)
        self.assertEqual(report["original_neon_action_gaps_in_previous_owner_snapshot"], 6)
        self.assertEqual(len(report["research_evidence_events"]), 6)
        src = {(r["stock_id"], r["ex_date"]): r
               for r in report["research_evidence_events"]}
        self.assertEqual(set(src), {
            (sid, day.isoformat()) for sid, day, *_ in gap.CANDIDATES})
        self.assertEqual(
            src[("1101", "2022-07-21")]["issuer_retrospective_cash_ntd_per_common_share"],
            "0.99928258")
        self.assertEqual(
            src[("1101", "2022-07-21")][
                "issuer_retrospective_stock_dividend_nominal_ntd_per_share"],
            "0.99928258")
        self.assertEqual(src[("1101", "2022-07-21")]["issuer_source"], m.ISSUER_TCC)
        self.assertIsNone(src[("1101", "2022-07-21")]["issuer_published_record_date_if_present"])
        self.assertEqual(src[("1101", "2022-07-21")]["issuer_published_cash_payment_date"],
                         "2022-08-22")
        for (sid, day), event in src.items():
            if sid == "2330":
                self.assertEqual(event["issuer_source"], m.ISSUER_TSMC)
                self.assertEqual(event["issuer_retrospective_cash_ntd_per_common_share"], "2.75")
                self.assertEqual(
                    event["issuer_retrospective_stock_dividend_nominal_ntd_per_share"], "0")
                self.assertTrue(event["issuer_published_record_date_if_present"])
            self.assertFalse(event["stock_dividend_new_shares_per_old_share_verified"])
            self.assertFalse(event["point_in_time_usable_in_trading_model"])
            self.assertFalse(event["economic_total_return_adjustment_approved"])

    def test_tsmc_record_and_distribution_dates_are_official_retrospective(self):
        events = {(r[0], r[1]): r for r in m.ISSUER_ECONOMICS}
        expected = {
            "2021-12-16": ("2021-12-22", "2022-01-13"),
            "2022-03-16": ("2022-03-22", "2022-04-14"),
            "2022-06-16": ("2022-06-22", "2022-07-14"),
            "2022-09-15": ("2022-09-21", "2022-10-13"),
            "2022-12-15": ("2022-12-21", "2023-01-12"),
        }
        for ex_date, (record, distributed) in expected.items():
            r = events[("2330", ex_date)]
            self.assertEqual((r[4], r[5]), (record, distributed))

    def test_tcc_revision_is_only_third_party_mirror_not_original_mops(self):
        report = m.evaluate(accepted_gap())
        claims = report["tcc_mops_mirror_claimed_revisions"]
        self.assertEqual([(r["claimed_date"], r["claimed_time"]) for r in claims],
                         [("2022-06-23", "19:53:53"),
                          ("2022-07-06", "18:49:23")])
        self.assertTrue(all(
            r["claim_provenance"] == "THIRD_PARTY_MOPS_REPRINT_NOT_ORIGINAL"
            for r in claims))
        self.assertFalse(report["mops_original_first_publication_timestamp_proven"])
        self.assertFalse(report["publication_vintage_and_asof_eligibility_verified"])
        self.assertFalse(report["tcc_stock_dividend_new_shares_factor_verified"])

    def test_gap_provenance_guard_rejects_fake_completeness_or_missing_event(self):
        baseline = accepted_gap()
        scalar_cases = [
            ("candidate_dates_without_stored_action", 5),
            ("stored_action_rows_in_entire_two_stock_window", 1),
            ("source_issuer_urls_checked_at_runtime", True),  # absent field
            ("private_prior_2330_and_1101_raw_source_receipts_guard_passed", False),
            ("known_event_candidates_prove_complete_action_universe", True),
            ("retrospective_event_date_is_original_publication_vintage", True),
            ("stock_dividend_adjustments_verified", True),
            ("cash_dividend_entitlement_and_payment_verified", True),
            ("real_future_return_labels_approved", True),
            ("production_backfill_approved", True),
            ("model_release", "READY"),
            ("line_messages_sent", 1),
            ("neon_writes", 1),
            ("paid_services_requested", True),
        ]
        # Only check mutations of fields explicitly required in the prior
        # contract. Unknown additive metadata is not material to the guard.
        scalar_cases = [x for x in scalar_cases if x[0] in baseline]
        for name, newval in scalar_cases:
            changed = dict(baseline, **{name: newval})
            with self.subTest(name=name), self.assertRaises(ValueError):
                m.verify_action_gap_receipt(changed)
        for modification in (
            {"stock_id": "1589"},
            {"candidate_ex_date": "2023-01-01"},
            {"status": "RECORDED_ACTION_EXISTS_UNRECONCILED"},
            {"same_date_stored_action_rows": 1},
            {"historical_total_return_label_approved": True},
            {"original_issuer_announcement_publication_timestamp_verified": True},
        ):
            changed = dict(baseline)
            changed["candidate_date_witnesses"] = [
                dict(item) for item in baseline["candidate_date_witnesses"]]
            changed["candidate_date_witnesses"][0].update(modification)
            with self.subTest(change=modification), self.assertRaises(ValueError):
                m.verify_action_gap_receipt(changed)
        missing = dict(baseline)
        missing["candidate_date_witnesses"] = baseline["candidate_date_witnesses"][:-1]
        with self.assertRaises(ValueError):
            m.verify_action_gap_receipt(missing)
        duplicated = dict(baseline)
        duplicated["candidate_date_witnesses"] = (
            baseline["candidate_date_witnesses"][:-1]
            + [dict(baseline["candidate_date_witnesses"][0])])
        with self.assertRaises(ValueError):
            m.verify_action_gap_receipt(duplicated)

    def test_incomplete_price_or_wrong_stock_amount_and_source_fail_closed(self):
        baseline = list(m.ISSUER_ECONOMICS)
        mutations = (
            (0, 2, "1"),   # never accept rounded interim TCC cash
            (0, 3, "0"),   # cannot omit share dividend
            (1, 2, "2.5"), # cannot use earlier-year TSMC rate
            (1, 3, "0.5"),
            (0, 6, "https://example.com/not-issuer"),
            (0, 4, "2022-07-27"), # no original record date column
            (1, 4, None),
            (0, 5, "2022-01-01"), # payment before ex-date
        )
        for idx, column, value in mutations:
            updated = [list(r) for r in baseline]
            updated[idx][column] = value
            with self.subTest(event=idx, field=column), self.assertRaises(ValueError):
                m.check_issuer_economics(updated)
        for bad in ("NaN", "Infinity", "-1", "2e3", "0.0" * 16):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m._safe_decimal(bad)
        with self.assertRaises(ValueError):
            m.check_issuer_economics(baseline[:-1])
        duplicate = list(baseline)
        duplicate[-1] = duplicate[0]
        with self.assertRaises(ValueError):
            m.check_issuer_economics(duplicate)

    def test_any_official_schedule_facts_still_leave_returns_model_blocked(self):
        result = m.evaluate(accepted_gap())
        for field in (
            "mops_original_first_publication_timestamp_proven",
            "tcc_stock_dividend_new_shares_factor_verified",
            "corporate_action_universe_complete",
            "publication_vintage_and_asof_eligibility_verified",
            "raw_price_adjustment_factors_verified",
            "real_forward_total_return_labels_approved",
            "production_backfill_approved",
            "owner_original_AES_ciphertexts_reauthenticated_in_this_run",
            "new_neon_snapshot_performed_in_this_run",
            "source_issuer_urls_checked_at_runtime",
        ):
            self.assertIs(result[field], False, field)
        self.assertEqual(result["model_release"], "BLOCKED")
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertFalse(result["paid_services_requested"])

    def test_owner_private_report_exclusive_create_and_no_overwrite(self):
        report = accepted_gap()
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            old = folder / "prior-private-report.json"
            target = folder / "new-private-report.json"
            old.write_text(json.dumps(report), encoding="utf-8")
            module = "scripts.twse_2021_22_owner_issuer_dividend_economics_offline"
            with patch(module + "._private_file",
                       side_effect=lambda p, should_exist: Path(p)):
                m.run_owner(prior_action_gap=old, out=target)
                private_result = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(private_result["reviewed_issuer_retrospective_event_rows"], 6)
                self.assertFalse(private_result["real_forward_total_return_labels_approved"])
                first = target.read_bytes()
                with self.assertRaises(m.IssuerEvidenceError) as failure:
                    m.run_owner(prior_action_gap=old, out=target)
                self.assertEqual(failure.exception.code, "PRIVATE_REPORT_WRITE")
                self.assertEqual(first, target.read_bytes())

    def test_preflight_invalid_prior_or_output_path_suppresses_raw_exception(self):
        secret = "postgresql://hidden@private-host/sensitive"
        with self.assertRaises(m.IssuerEvidenceError) as caught:
            m._phase("PRIOR_ACTION_GAP_GUARD", lambda: (_ for _ in ()).throw(
                ValueError(secret)))
        self.assertEqual(caught.exception.code, "PRIOR_ACTION_GAP_GUARD")
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, m._safe_error(secret))
        self.assertIn("diagnostic_stage=UNCLASSIFIED", m._safe_error(secret))

    def test_no_new_neon_archive_or_network_or_line_operations(self):
        # The script has neither operational network drivers nor price logic.
        import inspect
        code = inspect.getsource(m)
        for spelling in (
            "psycopg.connect(", "urllib.request.urlopen(", "requests.get(",
            "requests.post(", "encrypt_rows(", "verify_archive(",
        ):
            self.assertNotIn(spelling, code)
        self.assertNotIn("DAILY_PRICE_SQL", code)
        self.assertNotIn("INSERT INTO", code)
        self.assertNotIn("UPDATE public.corporate_actions", code)
