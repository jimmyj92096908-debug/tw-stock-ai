"""Synthetic official six-month 1101/2330 response proof, no live HTTP."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import twse_2021_22_owner_twse_six_event_months_readonly as m
from scripts import twse_2021_22_frozen2_official_action_monthly_audit as old
from scripts import twse_2021_22_owner_issuer_dividend_economics_offline as issuer
from scripts import twse_2021_22_owner_two_stock_action_gap_readonly as gap
from tests import test_twse_2021_22_owner_two_stock_action_gap_readonly as old_fixture


def owner_prior():
    base = gap.evaluate(
        prior=old_fixture.original(),
        actions=[], density=old_fixture.density(),
        event_days=old_fixture.real_event_days())
    return issuer.evaluate(base)


def official_row(sid, d, *, kind="ex", label="息"):
    if kind == "ex":
        return {"證券代號": sid, "除權息日期":
                f"{d.year - 1911}/{d.month:02d}/{d.day:02d}",
                "權或息": label, "除權息前收盤價": "100",
                "除權息參考價": "98"}
    return {"證券代號": sid, "恢復買賣日期":
            f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"}


def response(kind, begin, end, *, omit=None, extras=None, no_data=False):
    rows = []
    if not no_data:
        for sid, stamp in m.EXPECTED_EX_DATE_PAIRS:
            d = date.fromisoformat(stamp)
            if kind == "ex" and begin <= d <= end and (sid, stamp) != omit:
                rows.append(official_row(
                    sid, d, label="權息" if sid == "1101" else "息"))
        rows.append(official_row("1589", begin, kind=kind))
        for sid, d, k in extras or ():
            if kind == k and begin <= d <= end:
                rows.append(official_row(sid, d, kind=kind,
                                         label="息" if kind == "ex" else ""))
    payload = (
        {"stat": "很抱歉，沒有符合條件的資料", "data": []}
        if no_data else {"stat": "OK", "data": rows}
    )
    parsed = old.parse_month_response(
        payload, kind=kind, begin=begin, end=end,
        targets=m.STOCKS)
    return dict(
        parsed, response_sha256="a"*64,
        source_url=m.SOURCES[kind],
        requested_start=begin.isoformat(),
        requested_end=end.isoformat(),
    )


class TwoStockSixMonthsOfficialTests(unittest.TestCase):
    def test_bounded_calendar_keeps_2021_dec16_and_excludes_future_dec31(self):
        intervals = m.exact_months()
        self.assertEqual([i[0] for i in intervals], list(m.MONTHS))
        self.assertEqual(len(intervals), 6)
        self.assertEqual(intervals[0], ("2021-12", date(2021, 12, 1),
                                        date(2021, 12, 31)))
        self.assertEqual(intervals[-1], ("2022-12", date(2022, 12, 1),
                                         date(2022, 12, 30)))
        self.assertIn(("2330", "2021-12-16"), m.EXPECTED_EX_DATE_PAIRS)
        self.assertEqual(len(m.EXPECTED_EX_DATE_PAIRS), 6)

    def test_old_2327_2603_parser_remains_default_and_alt_uses_dec16(self):
        first, last = date(2021, 12, 1), date(2021, 12, 31)
        payload = {"stat":"OK", "data":[
            official_row("2330", date(2021,12,16)),
            official_row("2327", date(2021,12,30))
        ]}
        with self.assertRaises(ValueError):
            old.parse_month_response(payload, kind="ex", begin=first, end=last)
        verified = old.parse_month_response(
            payload, kind="ex", begin=first, end=last,
            targets=m.STOCKS)
        self.assertEqual(len(verified["events"]), 1)
        self.assertEqual(verified["events"][0]["stock_id"], "2330")
        self.assertEqual(verified["events"][0]["event_date"], "2021-12-16")
        with self.assertRaises(ValueError):
            old.parse_month_response(
                payload, kind="ex", begin=first, end=last,
                targets=frozenset(("1589", "2330")))
        # Previously accepted original frozen2 default market boundary.
        original = old.parse_month_response(
            {"stat":"OK", "data":[
                official_row("2327", date(2021,12,30))]},
            kind="ex", begin=date(2021,12,30),
            end=date(2021,12,31))
        self.assertEqual(original["events"][0]["stock_id"], "2327")

    def test_all_six_dates_with_official_ex_and_reduction_responses(self):
        calls = []
        def fetch(kind, begin, end):
            calls.append((kind, begin, end))
            return response(kind, begin, end)
        result = m.reconcile(owner_prior(), fetcher=fetch,
            captured_at_utc=datetime(2026, 11, 23, tzinfo=timezone.utc))
        self.assertEqual(len(calls), 12)
        self.assertEqual(result["official_twse_http_requests"], 12)
        self.assertEqual(result["expected_issuer_retrospective_event_date_count"], 6)
        self.assertEqual(result["expected_events_found_in_official_twse_ex_feed"], 6)
        self.assertTrue(result["all_six_known_dividend_dates_observed_in_twse_ex_feed"])
        self.assertEqual(result["expected_event_date_pairs_not_observed"], [])
        self.assertEqual(result["additional_twse_ex_date_pairs_in_same_six_months"], [])
        self.assertEqual(len(result["retrospective_event_date_witnesses"]), 6)
        self.assertTrue(all(
            x["official_twse_twt49u_matching_date_observed"]
            for x in result["retrospective_event_date_witnesses"]))
        self.assertTrue(any(
            "COMBINED_OR_UNCLASSIFIED" in x["twse_reported_categories"]
            for x in result["retrospective_event_date_witnesses"] if x["stock_id"]=="1101"))
        self.assertTrue(all(
            not x["official_event_economics_cash_share_amount_verified"]
            for x in result["retrospective_event_date_witnesses"]))
        self.assertFalse(result["original_mops_issuer_announcement_timestamps_verified"])
        self.assertFalse(result["official_data_retrieved_as_of_original_2021_22_publication"])
        self.assertFalse(result["full_2021_22_corporate_action_universe_verified"])
        self.assertFalse(result["verified_adjusted_total_return_labels"])
        self.assertFalse(result["production_neon_backfill_approved"])
        self.assertEqual(result["model_release"], "BLOCKED")
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["source_months_queried"], list(m.MONTHS))

    def test_no_data_or_missing_known_event_is_reported_never_promoted(self):
        target = ("2330", "2022-12-15")
        x = m.reconcile(owner_prior(), fetcher=lambda kind, begin, end:
                        response(kind, begin, end, omit=target))
        self.assertEqual(x["expected_events_found_in_official_twse_ex_feed"], 5)
        self.assertFalse(x["all_six_known_dividend_dates_observed_in_twse_ex_feed"])
        self.assertEqual(x["expected_event_date_pairs_not_observed"],
                         [{"stock_id":"2330", "ex_date":"2022-12-15"}])
        blank = m.reconcile(owner_prior(),
                            fetcher=lambda kind, begin, end:
                            response(kind, begin, end, no_data=True))
        self.assertEqual(blank["expected_events_found_in_official_twse_ex_feed"], 0)
        self.assertFalse(blank["all_six_known_dividend_dates_observed_in_twse_ex_feed"])
        self.assertEqual(len(blank["expected_event_date_pairs_not_observed"]), 6)
        self.assertEqual(blank["model_release"], "BLOCKED")

    def test_extra_official_ex_and_reduction_event_dates_preserved_as_leads(self):
        extra = [
            ("1101", date(2022, 9, 22), "ex"),
            ("2330", date(2022, 3, 25), "reduction"),
        ]
        report = m.reconcile(
            owner_prior(), fetcher=lambda kind, begin, end:
            response(kind, begin, end, extras=extra))
        self.assertEqual(report["additional_twse_ex_date_pairs_in_same_six_months"],
                         [{"stock_id": "1101", "ex_date": "2022-09-22"}])
        self.assertEqual(len(report["official_target_issuer_event_rows"]), 8)
        self.assertFalse(report["full_2021_22_corporate_action_universe_verified"])
        self.assertFalse(report["cash_stock_entitlement_and_par_factor_verified"])

    def test_cannot_pass_with_foreign_target_mismatch_or_tampered_receipt(self):
        for change in (
            {"scope": "NOT_OFFICIAL"},
            {"reviewed_issuer_retrospective_event_rows": 5},
            {"original_neon_action_gaps_in_previous_owner_snapshot": 5},
            {"source_issuer_urls_checked_at_runtime": True},
            {"model_release": "READY"},
            {"neon_writes": 1},
            {"mops_original_first_publication_timestamp_proven": True},
            {"real_forward_total_return_labels_approved": True},
        ):
            mutated = dict(owner_prior(), **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.reconcile(mutated, fetcher=lambda kind,b,e: response(kind,b,e))
        fake = dict(owner_prior())
        fake["research_evidence_events"] = [
            dict(x) for x in fake["research_evidence_events"]]
        fake["research_evidence_events"][0]["stock_id"] = "1589"
        with self.assertRaises(ValueError):
            m.validate_private_prior(fake)

    def test_spoofed_url_hash_duplicate_or_future_event_fail_closed(self):
        legit = response("ex", date(2022, 3, 1), date(2022, 3, 31))
        def corruption(c):
            def fetch(kind, begin, end):
                row = response(kind, begin, end)
                if kind == "ex" and begin.month == 3:
                    c(row)
                return row
            return fetch
        def corrupt_url(x): x["source_url"] = "https://evil.example/redirect"
        def corrupt_hash(x): x["response_sha256"] = "abcd"
        def dup(x): x["events"] *= 2; x["received_rows"] += 1
        def year_leak(x): x["events"][0]["event_date"] = "2023-01-01"
        def future_vintage(x): x["events"][0][
            "original_issuer_announcement_timestamp_available"] = True
        for fn in (corrupt_url, corrupt_hash, dup, year_leak, future_vintage):
            with self.subTest(mutation=fn.__name__), self.assertRaises(ValueError):
                m.reconcile(owner_prior(), fetcher=corruption(fn))
        self.assertGreater(len(legit["events"]), 0)

    def test_owner_private_output_exclusive_create_and_failure_sanitization(self):
        with TemporaryDirectory() as d:
            old_path, new_path = Path(d)/"prior.json", Path(d)/"proof.json"
            old_path.write_text(json.dumps(owner_prior()),encoding="utf-8")
            mod = "scripts.twse_2021_22_owner_twse_six_event_months_readonly"
            with patch(mod + "._private_file",
                       side_effect=lambda p,should_exist: Path(p)), \
                 patch(mod + ".fetch_month_kind",
                       side_effect=lambda kind,b,e,targets:
                       response(kind,b,e)) as requests:
                m.run_owner(prior=old_path, out=new_path)
                result = json.loads(new_path.read_text(encoding="utf-8"))
                self.assertEqual(result["official_twse_http_requests"], 12)
                self.assertEqual(requests.call_count, 12)
                before = new_path.read_bytes()
                with self.assertRaises(m.OwnerOfficialStageError) as problem:
                    m.run_owner(prior=old_path, out=new_path)
                self.assertEqual(problem.exception.code, "PRIVATE_REPORT_WRITE")
                self.assertEqual(before,new_path.read_bytes())
        secret = "postgresql://not-to-be-printed@private"
        with self.assertRaises(m.OwnerOfficialStageError) as ctx:
            m._phase("TWSE_OFFICIAL_MONTH_RESPONSES",
                     lambda: (_ for _ in ()).throw(ValueError(secret)))
        self.assertEqual(ctx.exception.code, "TWSE_OFFICIAL_MONTH_RESPONSES")
        self.assertNotIn(secret,str(ctx.exception))
        self.assertNotIn(secret,m.safe_error(secret))

    def test_no_sql_aes_or_adjusted_total_return_actions(self):
        import inspect
        script = inspect.getsource(m)
        for bad in (
            "psycopg.connect(", "UPDATE public.", "INSERT INTO",
            "requests.post(", "encrypt_rows(", "STOCK_ARCHIVE_KEY_HEX",
        ):
            self.assertNotIn(bad,script)
