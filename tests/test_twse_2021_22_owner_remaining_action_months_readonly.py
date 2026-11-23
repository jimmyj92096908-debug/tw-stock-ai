"""Synthetic incremental 8-month TWSE source proof: no real network or user files."""
from datetime import date, datetime, timezone
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import twse_2021_22_owner_remaining_action_months_readonly as m
from scripts import twse_2021_22_owner_twse_six_event_months_readonly as old
from scripts import twse_2021_22_frozen2_official_action_monthly_audit as parser
from tests.test_twse_2021_22_owner_twse_six_event_months_readonly import (
    owner_prior, response as previous_source_response, official_row,
)


def accepted_six():
    return old.reconcile(
        owner_prior(), fetcher=lambda kind,a,b:
        previous_source_response(kind,a,b),
        captured_at_utc=datetime(2026, 11, 23, 11, 1,
                                 tzinfo=timezone.utc),
    )


def missing_source_response(kind, begin, end, *, extras=(), no_data=False):
    rows = []
    if not no_data:
        rows = [official_row("1589", begin, kind=kind)]
        for sid, day, event_kind in extras:
            if begin <= day <= end and event_kind == kind:
                rows.append(official_row(sid, day, kind=kind))
    payload = (
        {"stat": "很抱歉，沒有符合條件的資料", "data": []}
        if no_data else {"stat": "OK", "data": rows}
    )
    parsed = parser.parse_month_response(
        payload, kind=kind, begin=begin, end=end, targets=m.STOCKS)
    return dict(
        parsed, response_sha256="b"*64,
        source_url=m.SOURCES[kind],
        requested_start=begin.isoformat(),
        requested_end=end.isoformat(),
    )


class RemainingEightMonthsTests(unittest.TestCase):
    def test_exact_eight_new_months_and_14_full_months_with_2021_nov23(self):
        self.assertEqual(len(m.MISSING_MONTHS), 8)
        self.assertEqual(len(m.COMPLETE_MONTHS), 14)
        self.assertEqual(len(m.FIRST_MONTHS), 6)
        self.assertEqual(m.month_bounds("2021-11"),
                         (date(2021, 11, 23), date(2021, 11, 30)))
        self.assertEqual(m.month_bounds("2022-12"),
                         (date(2022, 12, 1), date(2022, 12, 30)))
        self.assertEqual(
            set(m.MISSING_MONTHS) | set(m.FIRST_MONTHS),
            set(m.COMPLETE_MONTHS))
        self.assertFalse(set(m.MISSING_MONTHS) & set(m.FIRST_MONTHS))
        with self.assertRaises(ValueError):
            m.month_bounds("2021-10")

    def test_old_parser_remains_frozen2_default_but_alt_2021_nov_allowed(self):
        november_row = official_row("2330", date(2021, 11, 25))
        payload = {"stat": "OK", "data": [november_row]}
        with self.assertRaises(ValueError):
            parser.parse_month_response(
                payload, kind="ex", begin=date(2021, 11, 23),
                end=date(2021, 11, 30))
        p = parser.parse_month_response(
            payload, kind="ex", begin=date(2021, 11, 23),
            end=date(2021, 11, 30), targets=m.STOCKS)
        self.assertEqual(p["events"][0]["event_date"], "2021-11-25")
        with self.assertRaises(ValueError):
            parser.parse_month_response(
                payload, kind="ex", begin=date(2021, 11, 22),
                end=date(2021, 11, 30), targets=m.STOCKS)

    def test_real_six_synthetic_proof_must_have_full_twelve_consistent_receipts(self):
        prior = accepted_six()
        events, recs = m.validate_prior_six(prior)
        self.assertEqual(len(recs), 12)
        self.assertEqual({
            (r["stock_id"], r["event_date"])
            for r in events if r["reported_event_category"] != "CAPITAL_REDUCTION"
        }, set(m.EXPECTED_EX_DATE_PAIRS))
        for field,val in (
            ("expected_events_found_in_official_twse_ex_feed", 5),
            ("original_mops_issuer_announcement_timestamps_verified", True),
            ("verified_adjusted_total_return_labels", True),
            ("all_six_known_dividend_dates_observed_in_twse_ex_feed", False),
            ("production_neon_backfill_approved", True),
            ("model_release", "RELEASED"),
            ("neon_writes", 1),
        ):
            changed=copy.deepcopy(prior)
            changed[field]=val
            with self.subTest(field=field), self.assertRaises(ValueError):
                m.validate_prior_six(changed)
        changed=copy.deepcopy(prior)
        changed["official_target_issuer_event_rows"][0]["stock_id"]="1589"
        with self.assertRaises(ValueError):
            m.validate_prior_six(changed)
        changed=copy.deepcopy(prior)
        changed["official_response_receipts"][0]["two_current_issuer_event_rows"]=999
        with self.assertRaises(ValueError):
            m.validate_prior_six(changed)
        changed=copy.deepcopy(prior)
        changed["official_response_receipts"].pop()
        with self.assertRaises(ValueError):
            m.validate_prior_six(changed)
        changed=copy.deepcopy(prior)
        changed["retrospective_event_date_witnesses"][0][
            "original_issuer_publication_timestamp_proven"]=True
        with self.assertRaises(ValueError):
            m.validate_prior_six(changed)

    def test_all_eight_months_16_calls_and_previous_six_preserved(self):
        calls = []
        def fetch(kind,start,end):
            calls.append((kind,start,end))
            return missing_source_response(kind,start,end)
        report=m.reconcile(accepted_six(),fetcher=fetch,
            observed_at=datetime(2026,11,23,12,18,tzinfo=timezone.utc))
        self.assertEqual(len(calls),16)
        self.assertEqual(report["new_official_twse_http_requests"],16)
        self.assertEqual(report["all_official_twse_http_response_receipts_count"],28)
        self.assertEqual(len(report["all_official_response_receipts"]),28)
        self.assertEqual(len(report["full_calendar_months_with_response_receipts"]),14)
        self.assertTrue(report["prior_six_issuer_date_matches_preserved"])
        self.assertEqual(report["original_six_known_issuer_ex_dividend_pairs"],6)
        self.assertEqual(report["additional_issuer_ex_right_dates_observed_in_new_eight_months"],[])
        self.assertEqual(report["additional_issuer_reduction_dates_observed_in_new_eight_months"],[])
        self.assertTrue(report[
            "new_months_without_observed_issuer_ex_right_rows_does_not_prove_no_events"])
        self.assertFalse(report["no_data_response_proves_zero_historic_company_actions"])
        self.assertFalse(report["response_source_historic_action_coverage_independently_proven_exhaustive"])
        self.assertFalse(report["issuer_original_mops_first_announcement_publication_verified"])
        self.assertFalse(report["full_five_year_dividends_or_prices_complete"])
        self.assertFalse(report["historical_pit_listing_universe_verified"])
        self.assertFalse(report["adjusted_total_return_labels_approved"])
        self.assertFalse(report["production_neon_backfill_approved"])
        self.assertEqual(report["neon_writes"],0)
        self.assertEqual(report["line_messages_sent"],0)
        self.assertFalse(report["paid_services_used"])
        self.assertEqual(report["model_release"],"BLOCKED")
        self.assertIn(("ex",date(2021,11,23),date(2021,11,30)),calls)
        self.assertNotIn(("ex",date(2021,12,1),date(2021,12,31)),calls)

    def test_new_extra_dividend_and_reduction_events_remain_unverified_leads(self):
        extra=[
            ("2330",date(2022,1,11),"ex"),
            ("1101",date(2021,11,26),"reduction"),
        ]
        report=m.reconcile(accepted_six(),
            fetcher=lambda kind,start,end:
            missing_source_response(kind,start,end,extras=extra))
        self.assertEqual(
            report["additional_issuer_ex_right_dates_observed_in_new_eight_months"],
            [{"stock_id":"2330","event_date":"2022-01-11",
              "official_category":"CASH_DIVIDEND"}])
        self.assertEqual(
            report["additional_issuer_reduction_dates_observed_in_new_eight_months"],
            [{"stock_id":"1101","event_date":"2021-11-26"}])
        self.assertFalse(report["issuer_original_mops_first_announcement_publication_verified"])
        self.assertFalse(report["adjusted_total_return_labels_approved"])

    def test_no_data_treated_as_unknown_never_zero_history(self):
        result=m.reconcile(accepted_six(),
            fetcher=lambda kind,a,b:
            missing_source_response(kind,a,b,no_data=True))
        self.assertEqual(result["new_official_twse_http_requests"],16)
        self.assertFalse(result["no_data_response_proves_zero_historic_company_actions"])
        self.assertFalse(result["response_source_historic_action_coverage_independently_proven_exhaustive"])
        self.assertEqual(result["model_release"],"BLOCKED")

    def test_source_spoofed_date_event_hash_duplicate_and_vintage_fail_closed(self):
        bad_modifications=[
            lambda r: r.update({"source_url":"http://evil.example/path"}),
            lambda r: r.update({"response_sha256":"NOT_SHA256"}),
            lambda r: r.update({"requested_start":"2022-01-02"}),
            lambda r: r.update({"received_rows":-1}),
        ]
        extra=[("1101",date(2022,1,11),"ex")]
        def fake(kind,a,b,mutator=None):
            result=missing_source_response(kind,a,b,extras=extra)
            if kind=="ex" and a.month==1 and a.year==2022 and mutator:
                mutator(result)
            return result
        for fn in bad_modifications:
            with self.subTest(fn=str(fn)),self.assertRaises(ValueError):
                m.reconcile(accepted_six(),
                    fetcher=lambda kind,a,b:
                    fake(kind,a,b,mutator=fn))
        for mutate in (
            lambda r:r["events"].append(dict(r["events"][0])),
            lambda r:r["events"][0].update({"stock_id":"1589"}),
            lambda r:r["events"][0].update({"event_date":"2023-01-01"}),
            lambda r:r["events"][0].update({
                "original_issuer_announcement_timestamp_available":True}),
            lambda r:r["events"][0].update({"reported_event_category":"CAPITAL_REDUCTION"}),
        ):
            def fetch(kind,a,b):
                rec=fake(kind,a,b)
                if kind=="ex" and a.month==1 and a.year==2022:
                    mutate(rec)
                    rec["received_rows"]=max(rec["received_rows"],len(rec["events"]))
                return rec
            with self.subTest(mutation=str(mutate)),self.assertRaises(ValueError):
                m.reconcile(accepted_six(),fetcher=fetch)

    def test_private_report_exclusive_output_and_sanitized_diagnostics(self):
        with TemporaryDirectory() as folder:
            oldfile=Path(folder)/"source.json"
            outfile=Path(folder)/"new.json"
            oldfile.write_text(json.dumps(accepted_six()),encoding="utf-8")
            mod="scripts.twse_2021_22_owner_remaining_action_months_readonly"
            with patch(mod+"._private_file",
                       side_effect=lambda p,should_exist:Path(p)), \
                 patch(mod+".fetch_month_kind",
                       side_effect=lambda kind,start,end,targets:
                       missing_source_response(kind,start,end)) as fetch:
                m.run_owner(prior=oldfile,out=outfile)
                report=json.loads(outfile.read_text(encoding="utf-8"))
                self.assertEqual(report["new_official_twse_http_requests"],16)
                self.assertEqual(fetch.call_count,16)
                original=outfile.read_bytes()
                with self.assertRaises(m.HistoricalStageError) as err:
                    m.run_owner(prior=oldfile,out=outfile)
                self.assertEqual(err.exception.code,"PRIVATE_REPORT_WRITE")
                self.assertEqual(outfile.read_bytes(),original)
        secret="postgresql://private_password@non-public-neon"
        with self.assertRaises(m.HistoricalStageError) as caught:
            m._phase("REMAINING_EIGHT_MONTH_OFFICIAL_HTTP",
                     lambda: (_ for _ in ()).throw(ValueError(secret)))
        self.assertEqual(caught.exception.code,"REMAINING_EIGHT_MONTH_OFFICIAL_HTTP")
        self.assertNotIn(secret,str(caught.exception))
        self.assertNotIn(secret,m.safe_error(secret))

    def test_no_database_aes_or_line_write_calls(self):
        import inspect
        source=inspect.getsource(m)
        for forbidden in (
            "psycopg.connect(","INSERT INTO","UPDATE public.",
            "DATABASE_URL", "STOCK_ARCHIVE_KEY_HEX", "encrypt_rows(",
            "requests.post(", "line_messages_sent\": 1",
        ):
            self.assertNotIn(forbidden,source)
