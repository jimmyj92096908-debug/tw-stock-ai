"""Offline, fully synthetic blocked 1101/2330 retrospective action gap tests."""
from datetime import date
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path

from scripts import twse_2021_22_owner_two_stock_action_gap_readonly as m


def prior(sid):
    return {
        "schema_version": 1,
        "scope": m.SCOPE_2330 if sid == "2330" else m.SCOPE_1101,
        "stock_id": sid,
        "as_of": "2022-12-30",
        "virtual_2021_22_combined_source_days": 274,
        "virtual_2022_source_calendar_days": 246,
        "neon_AES_overlapping_2330_source_stockdate_keys": 190,
        "neon_AES_overlapping_stockdate_keys": 190,
        "neon_AES_overlap_OHLCV_exact": True,
        "as_of_raw_prefix_source_days": 274,
        "source_rows_after_asof_used_in_computation": 0,
        "raw_unadjusted_sma240_is_tradable_signal": False,
        "all_five_year_market_data_complete": False,
        "survivorship_free_historical_universe_verified": False,
        "corporate_action_and_publication_vintage_verified": False,
        "authoritative_holdout_alpha_verified": False,
        "production_backfill_approved": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
        "model_release": "BLOCKED",
    }


def original():
    return {"1101": prior("1101"), "2330": prior("2330")}


def density():
    return [
        {"stock_id": sid, "y2021": 28, "y2022": 246}
        for sid in m.STOCKS
    ]


def real_event_days():
    return [
        {"stock_id": sid, "trade_date": day, "n": 1}
        for sid, day, *_ in m.CANDIDATES
    ]


class TwoStockActionGapTests(TestCase):
    def calculate(self, *, receipts=None, action_rows=None,
                  issuer_density=None, days=None):
        return m.evaluate(
            prior=original() if receipts is None else receipts,
            actions=[] if action_rows is None else action_rows,
            density=density() if issuer_density is None else issuer_density,
            event_days=real_event_days() if days is None else days,
        )

    def test_exact_public_event_date_candidates_missing_from_live_store(self):
        report = self.calculate()
        self.assertEqual(report["scope"], m.SCOPE)
        self.assertEqual(report["historical_candidate_event_dates"], 6)
        self.assertEqual(report["stored_action_rows_in_entire_two_stock_window"], 0)
        self.assertEqual(report["candidate_dates_without_stored_action"], 6)
        self.assertEqual(report["stored_action_rows_by_stock"], {"1101": 0, "2330": 0})
        self.assertEqual(report["neon_issuer_raw_source_days"], {"1101": 274, "2330": 274})
        self.assertEqual(report["current_eligible_stocks"], ["1101", "2330"])
        self.assertEqual(
            {(x["stock_id"], x["candidate_ex_date"]) for x
             in report["candidate_date_witnesses"]},
            {(sid, d.isoformat()) for sid, d, *_ in m.CANDIDATES})
        self.assertEqual(
            {x["retrospective_evidence_tier"] for x in report["candidate_date_witnesses"]},
            {"THIRD_PARTY_RETROSPECTIVE", "ISSUER_RETROSPECTIVE"},
        )
        self.assertTrue(all(x["official_raw_stock_day_exists"] for x in report["candidate_date_witnesses"]))
        self.assertTrue(all(x["status"] == "NO_ACTION_RECORD_ON_CANDIDATE_DATE"
                            for x in report["candidate_date_witnesses"]))
        self.assertFalse(report["retrospective_event_date_is_original_publication_vintage"])
        self.assertFalse(report["known_event_candidates_prove_complete_action_universe"])
        self.assertFalse(report["stock_dividend_adjustments_verified"])
        self.assertFalse(report["cash_dividend_entitlement_and_payment_verified"])
        self.assertFalse(report["capital_reduction_and_split_universe_verified"])
        self.assertFalse(report["tax_fee_reinvestment_and_total_return_verified"])
        self.assertFalse(report["adjusted_prices_or_raw_sma240_promoted_to_trading_signal"])
        self.assertFalse(report["real_future_return_labels_approved"])
        self.assertFalse(report["production_backfill_approved"])
        self.assertFalse(report["prior_receipts_are_cryptographically_reauthenticated_here"])
        self.assertEqual(report["model_release"], "BLOCKED")
        self.assertEqual(report["neon_writes"], 0)
        self.assertEqual(report["line_messages_sent"], 0)
        self.assertFalse(report["paid_services_requested"])

    def test_stored_event_same_date_does_not_promote_total_return(self):
        sid, day, *_ = m.CANDIDATES[0]
        r = {"stock_id": sid, "ex_date": day,
             "action_type": "CASH_DIVIDEND", "verified": True}
        report = self.calculate(action_rows=[r])
        self.assertEqual(report["stored_action_rows_in_entire_two_stock_window"], 1)
        self.assertEqual(report["candidate_dates_without_stored_action"], 5)
        match = next(c for c in report["candidate_date_witnesses"]
                     if c["stock_id"] == sid)
        self.assertEqual(match["same_date_stored_verified_action_rows"], 1)
        self.assertEqual(match["status"], "RECORDED_ACTION_EXISTS_UNRECONCILED")
        self.assertFalse(match["historical_total_return_label_approved"])
        self.assertFalse(report["real_future_return_labels_approved"])
        self.assertEqual(report["model_release"], "BLOCKED")

    def test_unrelated_record_does_not_prove_no_other_missing_events(self):
        report = self.calculate(action_rows=[{
            "stock_id": "2330", "ex_date": date(2022, 7, 1),
            "action_type": "CAPITAL_REDUCTION", "verified": False,
        }])
        self.assertEqual(report["stored_action_rows_by_stock"]["2330"], 1)
        self.assertEqual(report["candidate_dates_without_stored_action"], 6)
        self.assertFalse(report["known_event_candidates_prove_complete_action_universe"])

    def test_source_bar_event_date_absence_or_extra_day_fails(self):
        no_day = real_event_days()[1:]
        with self.assertRaises(ValueError):
            self.calculate(days=no_day)
        too_many = real_event_days()
        too_many[0] = dict(too_many[0], n=2)
        with self.assertRaises(ValueError):
            self.calculate(days=too_many)
        duplicated = real_event_days() + real_event_days()[:1]
        with self.assertRaises(ValueError):
            self.calculate(days=duplicated)
        foreign = real_event_days()
        foreign[0] = dict(foreign[0], stock_id="1589")
        with self.assertRaises(ValueError):
            self.calculate(days=foreign)
        outside = real_event_days()
        outside[0] = dict(outside[0], trade_date=date(2023, 1, 1))
        with self.assertRaises(ValueError):
            self.calculate(days=outside)

    def test_receipt_drift_or_unapproved_issuer_is_blocked(self):
        for sid in m.STOCKS:
            for mutation in (
                {"neon_writes": 1}, {"model_release": "READY"},
                {"source_rows_after_asof_used_in_computation": 1},
                {"corporate_action_and_publication_vintage_verified": True},
                {"survivorship_free_historical_universe_verified": True},
                {"raw_unadjusted_sma240_is_tradable_signal": True},
                {"neon_AES_overlap_OHLCV_exact": False},
                {"paid_services_used": True}, {"stock_id": "1589"},
            ):
                base = original()
                base[sid] = dict(base[sid], **mutation)
                with self.subTest(sid=sid, mutation=mutation), self.assertRaises(ValueError):
                    self.calculate(receipts=base)
        removed = original()
        del removed["1101"]
        with self.assertRaises(ValueError):
            self.calculate(receipts=removed)

    def test_source_density_or_stored_actions_drift_rejected(self):
        for n in (27, 245, 247):
            wrong = density()
            wrong[0] = dict(wrong[0], y2022=n)
            with self.assertRaises(ValueError):
                self.calculate(issuer_density=wrong)
        with self.assertRaises(ValueError):
            self.calculate(issuer_density=density()[:1])
        for act in (
            {"stock_id": "1589", "ex_date": date(2022, 7, 21),
             "action_type": "CASH_DIVIDEND", "verified": True},
            {"stock_id": "2330", "ex_date": date(2023, 1, 1),
             "action_type": "CASH_DIVIDEND", "verified": True},
            {"stock_id": "2330", "ex_date": date(2022, 6, 16),
             "action_type": "CASH_DIVIDEND", "verified": None},
            {"stock_id": "2330", "ex_date": date(2022, 6, 16),
             "action_type": "", "verified": True},
        ):
            with self.subTest(act=act), self.assertRaises(ValueError):
                self.calculate(action_rows=[act])
        with self.assertRaises(ValueError):
            self.calculate(action_rows=[{
                "stock_id": "2330", "ex_date": date(2022, 6, 16),
                "action_type": "CASH_DIVIDEND", "verified": True,
            }] * (m.MAX_EVENTS + 1))

    def test_sql_is_strict_read_only_bounded_and_never_prints_prices(self):
        for query in (m.COUNT_ACTION_SQL, m.ACTION_SQL,
                      m.PRICE_DENSITY_SQL, m.EVENT_DAY_SQL):
            for phrase in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "ALTER "):
                self.assertNotIn(phrase, query.upper())
        self.assertIn("LIMIT 101", m.ACTION_SQL)
        self.assertIn("LIMIT 20", m.EVENT_DAY_SQL)
        self.assertIn("stock_id=ANY(%s::varchar[])", m.ACTION_SQL)
        self.assertIn("COUNT(DISTINCT trade_date)", m.PRICE_DENSITY_SQL)
        self.assertNotIn("close,", m.ACTION_SQL)
        self.assertNotIn("cash_amount", m.ACTION_SQL)
        self.assertNotIn("price_factor", m.ACTION_SQL)

    def test_failure_codes_hide_raw_secrets_and_emit_only_allowlist(self):
        secret = "postgresql://owner-secret@secret-host/privateprice"
        with self.assertRaises(m.ActionGapStageError) as error:
            m._phase("NEON_READONLY_SNAPSHOT", lambda: (_ for _ in ()).throw(ValueError(secret)))
        self.assertEqual(error.exception.code, "NEON_READONLY_SNAPSHOT")
        self.assertNotIn(secret, str(error.exception))
        self.assertIn("diagnostic_stage=NEON_READONLY_SNAPSHOT", m._fail(error.exception.code))
        self.assertNotIn(secret, m._fail(secret))
        self.assertIn("diagnostic_stage=UNCLASSIFIED", m._fail(secret))

    def test_private_paths_fail_before_neon_or_report_writes(self):
        module = "scripts.twse_2021_22_owner_two_stock_action_gap_readonly"
        with patch(module + "._private_file", side_effect=ValueError("private price path")), \
             patch(module + ".capture_snapshot") as neon:
            with self.assertRaises(m.ActionGapStageError) as failure:
                m.run_owner(report_2330="unused", report_1101="unused",
                            out="unused", database_url="unused")
        self.assertEqual(failure.exception.code, "PRIVATE_RECEIPTS")
        neon.assert_not_called()

    def test_prev_receipts_not_cryptographic_resign_of_owner_evidence(self):
        report = self.calculate()
        self.assertFalse(report["prior_receipts_are_cryptographically_reauthenticated_here"])
        self.assertFalse(report["retrospective_event_date_is_original_publication_vintage"])
        self.assertEqual(
            sum(x["retrospective_evidence_tier"] == "ISSUER_RETROSPECTIVE"
                for x in report["candidate_date_witnesses"]), 5)
        self.assertEqual(
            sum(x["retrospective_evidence_tier"] == "THIRD_PARTY_RETROSPECTIVE"
                for x in report["candidate_date_witnesses"]), 1)


    def test_six_exact_issuer_date_pairs_not_twelve_cross_product(self):
        """Regression: independent ANY(stock) + ANY(date) yielded 12 rows."""
        expected = {(sid, day) for sid, day, *_ in m.CANDIDATES}
        all_issuers_all_dates = {
            (sid, day) for sid in m.STOCKS
            for day in {d for _, d, *_ in m.CANDIDATES}
        }
        self.assertEqual(len(expected), 6)
        self.assertEqual(len(all_issuers_all_dates), 12)
        self.assertEqual(len(all_issuers_all_dates - expected), 6)
        self.assertIn("UNNEST(%s::varchar[], %s::date[])", m.EVENT_DAY_SQL)
        self.assertIn("p.stock_id = w.stock_id", m.EVENT_DAY_SQL)
        self.assertIn("p.trade_date = w.trade_date", m.EVENT_DAY_SQL)
        self.assertIn("FROM requested w", m.EVENT_DAY_SQL)
        self.assertNotIn("AND stock_id=ANY(%s::varchar[])", m.EVENT_DAY_SQL)
        self.assertNotIn("AND trade_date=ANY(%s::date[])", m.EVENT_DAY_SQL)
        # The original validation must remain STRICT: extra rows still fail.
        unexpected = next(iter(all_issuers_all_dates - expected))
        with self.assertRaises(ValueError):
            self.calculate(days=real_event_days() + [{
                "stock_id": unexpected[0], "trade_date": unexpected[1], "n": 1
            }])

    def test_capture_snapshot_restricts_exact_issuer_date_pair_parameters(self):
        """Simulate SELECT result contracts, asserting the query's bound pairs."""
        import psycopg
        from unittest.mock import patch

        class Rows:
            def __init__(self, items):
                self.items = items
            def fetchall(self):
                return self.items
            def fetchone(self):
                return self.items[0]

        class SafeFakeConnection:
            def __init__(self):
                self.readonly = False
                self.event_pairs = None
                self.executed = []
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def execute(self, query, args=None):
                self.executed.append(query)
                if query == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY":
                    self.readonly = True
                    return Rows([])
                if query.startswith("SET LOCAL "):
                    return Rows([])
                if query == m.ELIGIBLE_SQL:
                    return Rows([{"stock_id": sid} for sid in
                                 ["1101", "2330"] + [f"S{i:04d}" for i in range(1090)]])
                if query == m.COUNT_ACTION_SQL:
                    self.test_case.assertEqual(args, (list(m.STOCKS), m.START, m.END))
                    return Rows([{"n": 0}])
                if query == m.ACTION_SQL:
                    return Rows([])
                if query == m.PRICE_DENSITY_SQL:
                    return Rows(density())
                if query == m.EVENT_DAY_SQL:
                    self.test_case.assertTrue(self.readonly)
                    self.event_pairs = list(zip(*args))
                    expected = {(sid, day) for sid, day, *_ in m.CANDIDATES}
                    self.test_case.assertEqual(set(self.event_pairs), expected)
                    self.test_case.assertEqual(len(self.event_pairs), 6)
                    return Rows(real_event_days())
                raise AssertionError("Unexpected or unsafe source query")
        connection = SafeFakeConnection()
        connection.test_case = self
        with patch.object(psycopg, "connect", return_value=connection) as connect:
            actions, issuer_density, observed_days = m.capture_snapshot(
                "postgresql://nonsecret-synthetic")
        self.assertTrue(connection.readonly)
        self.assertEqual(actions, [])
        self.assertEqual(issuer_density, density())
        self.assertEqual(len(observed_days), 6)
        report = self.calculate(
            action_rows=actions, issuer_density=issuer_density,
            days=observed_days)
        self.assertEqual(report["candidate_dates_without_stored_action"], 6)
        self.assertEqual(report["model_release"], "BLOCKED")
        connect.assert_called_once()
        self.assertEqual(
            connect.call_args.kwargs["options"],
            "-c default_transaction_read_only=on")
