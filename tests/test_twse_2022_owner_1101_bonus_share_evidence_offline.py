"""Offline 1101 TCC new-share *candidate* audit, synthetic prior evidence only."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from scripts import twse_2022_owner_1101_bonus_share_evidence_offline as m
from scripts import twse_2021_22_owner_remaining_action_months_readonly as prior_module
from tests.test_twse_2021_22_owner_remaining_action_months_readonly import (
    accepted_six, missing_source_response,
)


def accepted_fourteen():
    return prior_module.reconcile(
        accepted_six(), fetcher=lambda kind, a, b:
        missing_source_response(kind, a, b))


class TccBonusShareEvidenceTests(unittest.TestCase):
    def test_prior_real_contract_28_source_receipts_and_six_exact_days(self):
        report = accepted_fourteen()
        self.assertTrue(m.validate_prior(report))
        self.assertEqual(len(report["all_official_response_receipts"]), 28)
        self.assertEqual(len(report["all_official_target_issuer_event_rows"]), 6)
        self.assertEqual(report["new_official_twse_http_requests"], 16)

    def test_separate_ntd_nominal_bonus_from_new_shares_per_original(self):
        report = m.evaluate(accepted_fourteen())
        self.assertEqual(report["scope"], m.SCOPE)
        self.assertEqual(report["issuer_stock_id"], "1101")
        self.assertEqual(report["retrospective_ex_right_date"], "2022-07-21")
        self.assertEqual(
            report["candidate_nominal_share_dividend_ntd_per_old_share"],
            "0.99928258")
        self.assertEqual(report["candidate_cash_dividend_ntd_per_old_share"],
                         "0.99928258")
        self.assertEqual(report["candidate_new_shares_per_old_share"],
                         "0.099928258")
        self.assertEqual(report["candidate_new_shares_per_1000_old_shares"],
                         "99.928258")
        self.assertEqual(report["candidate_capital_ntd_reconstruction"],
                         "6116173400")
        self.assertEqual(Decimal("611617340")*Decimal("10"),
                         Decimal("6116173400"))
        self.assertEqual(Decimal("0.99928258")/Decimal("10")*Decimal("1000"),
                         Decimal("99.928258"))
        self.assertEqual(report["third_party_claimed_issuance_new_common_shares"],
                         "611617340")
        self.assertEqual(report["third_party_claimed_treasury_stock_in_revision"],
                         "4669600")
        self.assertEqual(
            report["third_party_claimed_amendment_publication"],
            "2022-07-06 18:49:23")
        self.assertTrue(report["historical_arithmetic_between_separately_republished_sources_matches"])
        self.assertTrue(report["first_party_current_retrospective_and_third_party_reprints_kept_distinct"])

    def test_arithmetic_match_does_not_authenticate_mops_pit_or_return(self):
        r = m.evaluate(accepted_fourteen())
        for blocked in (
            "original_mops_publication_byte_archive_authenticated",
            "original_mops_first_publication_timestamp_authenticated",
            "capital_increase_final_registry_authenticated",
            "investor_received_exact_entitlement_and_fractional_share_rule_verified",
            "per_old_share_bonus_factor_approved_for_price_adjustment",
            "cash_dividend_actual_entitlement_and_payment_verified",
            "corporate_actions_exhaustive_for_all_sources_and_all_years",
            "strict_historical_point_in_time_availability_verified",
            "forward_adjusted_total_return_labels_approved",
            "production_neon_backfill_approved",
            "owner_AES_archives_reauthenticated_in_this_run",
            "neon_requeried_in_this_run",
            "all_three_sources_requeried_live_at_runtime",
            "historical_original_mops_economics_fully_authenticated",
        ):
            self.assertIs(r[blocked], False, blocked)
        self.assertIs(r["all_source_interval_month_response_receipts_captured"], True)
        self.assertEqual(r["model_release"], "BLOCKED")
        self.assertEqual(r["neon_writes"], 0)
        self.assertEqual(r["line_messages_sent"], 0)
        self.assertFalse(r["paid_services_used"])

    def test_numeric_source_candidate_mutations_rejected(self):
        for field, changed in (
            ("stock_id","1589"),
            ("ex_right_dividend_date","2023-07-21"),
            ("cash_dividend_ntd_per_old_share_on_current_issuer_page","1"),
            ("stock_dividend_nominal_ntd_per_old_share_on_current_issuer_page",
             "0.99928258e0"),
            ("new_shares_in_reported_reprint","611617341"),
            ("new_common_share_par_ntd_in_reported_reprint","1"),
            ("bonus_capitalization_total_ntd_in_reported_reprint","6116173402"),
            ("bonus_new_shares_per_1000_old_shares_in_reprint","999.28258"),
            ("announced_cash_total_ntd_in_reprint","6116173400"),
            ("treasury_shares_not_reissued_in_revision_reprint","0"),
            ("amendment_claimed_date_and_time_third_party_only","2022-07-05 18:49:23"),
        ):
            modified = dict(m.CANDIDATE, **{field:changed})
            with self.subTest(field=field),self.assertRaises(ValueError):
                m.verify_candidate(modified)
        self.assertRaises(ValueError, m.verify_candidate,
                          dict(m.CANDIDATE, extraneous_unknown="foo"))
        self.assertRaises(ValueError, m.verify_candidate,
                          dict(m.CANDIDATE,
                               new_common_share_par_ntd_in_reported_reprint=float("nan")))
        self.assertEqual(m.verify_candidate()["candidate_new_shares_per_old_share"],
                         "0.099928258")

    def test_previous_14_month_research_tampering_fail_closed(self):
        base=accepted_fourteen()
        for key,value in (
            ("scope","unrecognized"),
            ("original_six_known_issuer_ex_dividend_pairs",5),
            ("new_official_twse_http_requests",12),
            ("all_official_twse_http_response_receipts_count",27),
            ("all_14_months_public_response_queries_adequately_covered",False),
            ("response_source_historic_action_coverage_independently_proven_exhaustive",True),
            ("issuer_original_mops_first_announcement_publication_verified",True),
            ("new_share_entitlement_and_cash_distribution_verified",True),
            ("production_neon_backfill_approved",True),
            ("neon_writes",1),
            ("model_release","RELEASED"),
            ("additional_issuer_ex_right_dates_observed_in_new_eight_months",
             [{"stock_id":"1101","event_date":"2022-08-11"}]),
        ):
            mutated=deepcopy(base)
            mutated[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                m.validate_prior(mutated)
        for mutation in (
            lambda x:x["all_official_response_receipts"].pop(),
            lambda x:x["all_official_response_receipts"][0].update(
                {"response_sha256_captured_now":"BAD_HASH"}),
            lambda x:x["all_official_response_receipts"][0].update(
                {"requested_start":"2022-01-01"}),
            lambda x:x["all_official_target_issuer_event_rows"][0].update(
                {"stock_id":"1589"}),
            lambda x:x["all_official_target_issuer_event_rows"][0].update(
                {"original_official_row_sha256":"BAD"}),
            lambda x:x["all_official_target_issuer_event_rows"].pop(),
        ):
            mutated=deepcopy(base)
            mutation(mutated)
            with self.subTest(mutation=str(mutation)),self.assertRaises(ValueError):
                m.validate_prior(mutated)
        duplicated=deepcopy(base)
        duplicated["all_official_response_receipts"][1] = deepcopy(
            duplicated["all_official_response_receipts"][0])
        with self.assertRaises(ValueError):
            m.validate_prior(duplicated)

    def test_guarded_owner_only_report_is_exclusive_create(self):
        with TemporaryDirectory() as folder:
            previous=Path(folder)/"prior.json"
            out=Path(folder)/"bonus.json"
            previous.write_text(json.dumps(accepted_fourteen()),encoding="utf-8")
            mod="scripts.twse_2022_owner_1101_bonus_share_evidence_offline"
            with patch(mod+"._private_file",
                       side_effect=lambda path,should_exist:Path(path)):
                m.run_owner(prior=previous,out=out)
                result=json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(result["model_release"],"BLOCKED")
                self.assertEqual(result["candidate_new_shares_per_old_share"],
                                 "0.099928258")
                saved=out.read_bytes()
                with self.assertRaises(m.BonusEvidenceError) as exc:
                    m.run_owner(prior=previous,out=out)
                self.assertEqual(exc.exception.stage,"PRIVATE_REPORT_WRITE")
                self.assertEqual(saved,out.read_bytes())

    def test_no_live_neon_mops_aes_or_market_prices_and_secret_safe_diagnostic(self):
        import inspect
        code=inspect.getsource(m)
        for forbidden in ("psycopg.connect(","requests.get(","requests.post(",
                          "urllib.request.urlopen(", "INSERT INTO", "UPDATE public.",
                          "DATABASE_URL","STOCK_ARCHIVE_KEY_HEX"):
            self.assertNotIn(forbidden,code)
        secret="postgresql://private-credential@hidden-host"
        with self.assertRaises(m.BonusEvidenceError) as x:
            m._phase("BONUS_RATIO_ECONOMICS_GUARD",
                     lambda: (_ for _ in ()).throw(ValueError(secret)))
        self.assertEqual(x.exception.stage,"BONUS_RATIO_ECONOMICS_GUARD")
        self.assertNotIn(secret, str(x.exception))
        self.assertNotIn(secret,m.safe_error(secret))
