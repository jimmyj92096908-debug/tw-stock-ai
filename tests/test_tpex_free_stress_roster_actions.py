"""Read-only Free storage, real listing universe and action-label safety gates."""
from datetime import date,datetime,timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import tpex_free_storage_stress as stress
from scripts import tpex_historical_roster_audit as roster
from scripts import audit_total_return_label_provenance as actions
from src.adjusted_prices import adjust_bars

ROOT=Path(__file__).resolve().parents[1]

def tables():
    return {
        "daily_prices":{"n":800000,"bytes":200000000},
        "daily_adjusted_prices":{"n":270000,"bytes":70000000},
        "daily_technicals":{"n":270000,"bytes":58000000},
        "daily_smc":{"n":270000,"bytes":52000000},
    }

def sources():
    return {"observed_anchored_days":1212,"covered_days":900,
            "incomplete_days":312}

def debt():
    return {"raw_prices":600000,"adjusted":100000,
            "technical":100000,"smc":100000}

def schema():
    return ["market","stock_id","stock_name","industry","updated_at"]

def membership():
    return {
        "current_master":898,
        "observed_price_stocks":898,
        "current_master_no_price":0,
        "price_stocks_not_in_current_master":0,
        "first_seen_last_three_years_not_verified_ipo":108,
        "current_master_1000_price_rows":16,
        "last_real_market_day":date(2026,11,20),
    }

def event(*,market="tpex",stock="8937",kind="CASH_DIVIDEND",
          eid="source_1",verified=True,factor="0.95",ex_date=date(2025,9,9),
          cash=None):
    return {
        "market":market,"stock_id":stock,"ex_date":ex_date,
        "action_type":kind,"price_factor":factor,"share_factor":"1",
        "cash_amount":cash,"stock_amount":None,"source_event_id":eid,
        "source":"TPEx_exDailyQ",
        "verified":verified,
        "created_at":datetime(2026,11,18,12,50,tzinfo=timezone.utc),
    }

def masters():
    return [{"market":"tpex","current_stocks":898},
            {"market":"twse","current_stocks":1093}]

class CapacityFreeStressTests(TestCase):
    def test_stress_tiers_include_indexes_future_factor_debt_and_guard(self):
        report=stress.forecast(db_bytes=400000000,tables=tables(),
            source=sources(),debts=debt())
        self.assertEqual(len(report["scenarios"]),3)
        self.assertEqual([r["new_quotes_per_unfilled_market_day_ASSUMPTION"]
                          for r in report["scenarios"]],[700,850,900])
        self.assertEqual(report["capacity_alert_level"],"BELOW_INTERNAL_ALERT")
        self.assertEqual(report["scenarios"][-1]["new_source_price_rows_STRESS"],
                         900*312)
        self.assertTrue(report["scenarios"][-1]["source_only_fits_with_reserve_ESTIMATE"])
        self.assertFalse(report["scenarios"][-1]["all_daily_factors_fit_with_reserve_ESTIMATE"])
        self.assertFalse(report["materialize_all_daily_factors_safe_under_max_stress"])
        self.assertEqual(report["existing_factor_debt_bytes_LOWER_BOUND_STRESS"],
             sum((600000-100000)*report["conservative_new_row_bytes"][k]
                 for k in ("daily_adjusted_prices","daily_technicals","daily_smc")))
        self.assertTrue(report["scenario_assumptions_not_historical_ipo_truth"])
        self.assertFalse(report["recommend_materialize_all_historical_factors_now"])
        self.assertTrue(report["database_read_only"])

    def test_alert_and_impossible_source_counts_fail(self):
        for db,level in ((630000000,"BELOW_INTERNAL_ALERT"),
                         (660000000,"WARNING"),
                         (755000000,"CRITICAL"),
                         (800000000,"STOP")):
            self.assertEqual(stress.forecast(db_bytes=db,tables=tables(),
                   source=sources(),debts=debt())["capacity_alert_level"],level)
        for broken in (
             {**sources(),"covered_days":899},
             {**sources(),"incomplete_days":True},
        ):
            with self.assertRaises(ValueError):
                stress.forecast(db_bytes=450000000,tables=tables(),source=broken,debts=debt())
        with self.assertRaises(ValueError):
            stress.forecast(db_bytes=450000000,tables={
                **tables(),"daily_smc":{"n":0,"bytes":0}},
                source=sources(),debts=debt())
        with self.assertRaises(ValueError):
            stress.forecast(db_bytes=450000000,tables=tables(),
                source=sources(),debts={**debt(),"smc":600001})

    def test_storage_sql_has_no_writes_and_readonly_connection(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def execute(sql,*args):
            out=MagicMock()
            if sql==stress.CAPACITY_SQL: out.fetchone.return_value={"bytes":450000000}
            if sql==stress.TABLE_SQL: out.fetchall.return_value=[
                {"tbl":key,**value} for key,value in tables().items()]
            if sql==stress.SOURCE_SQL: out.fetchone.return_value=sources()
            if sql==stress.DEBT_SQL: out.fetchone.return_value=debt()
            return out
        conn.execute.side_effect=execute
        with patch.object(stress.psycopg,"connect",return_value=conn) as c:
            r=stress.inspect("protected")
        self.assertEqual(r["database_bytes"],450000000)
        self.assertIn("default_transaction_read_only=on",c.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ READ ONLY",conn.execute.call_args_list[0].args[0])
        for sql in (stress.TABLE_SQL,stress.SOURCE_SQL,stress.DEBT_SQL,stress.CAPACITY_SQL):
            self.assertNotIn("INSERT INTO",sql.upper())
            self.assertNotIn("DELETE FROM",sql.upper())
            self.assertNotIn("UPDATE public.",sql.upper())

class HistoricalListingAndDelistingAuditTests(TestCase):
    def test_current_stock_master_is_not_historic_membership(self):
        report=roster.evaluate(schema(),membership(),[])
        self.assertEqual(report["today_master_stocks"],898)
        self.assertEqual(report["original_prices_distinct_stocks"],898)
        self.assertEqual(report["recent_first_seen_not_proven_ipo"],108)
        self.assertEqual(report["missing_historic_listing_effective_date_fields"],
                         ["delisting_effective_date","listing_effective_date"])
        self.assertFalse(report["original_as_of_listing_and_delisting_archive_proven"])
        self.assertFalse(report["historical_survivorship_free_investible_roster_approved"])
        self.assertTrue(report["first_saved_price_is_not_exchange_ipo_date"])
        with self.assertRaises(PermissionError):
            roster.require_historical_universe(report)

    def test_missing_issuer_snapshot_cannot_be_filled_by_price_history(self):
        for broken in (
           {**membership(),"current_master_no_price":899},
           {**membership(),"first_seen_last_three_years_not_verified_ipo":899},
           {**membership(),"price_stocks_not_in_current_master":-1},
           {**membership(),"current_master":True},
        ):
            with self.assertRaises(ValueError):
                roster.evaluate(schema(),broken,[])
        with self.assertRaises(ValueError):
            roster.evaluate(schema()[:-1],membership(),[])
        with self.assertRaises(ValueError):
            roster.evaluate(schema(),membership(),[
                {"stock_id":"1234","first_price_day":date(2022,1,1)}])
        self.assertIn("first_seen_last_three_years_not_verified_ipo",roster.HISTORY_SUMMARY_SQL)
        self.assertIn("price_rows",roster.NONMASTER_SAMPLE_SQL)

    def test_no_listing_date_claim_from_current_master_updated_at(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def execute(sql,*args):
            r=MagicMock()
            if sql==roster.CURRENT_STOCK_COLUMNS_SQL:
                r.fetchall.return_value=[{"column_name":s} for s in schema()]
            elif sql==roster.HISTORY_SUMMARY_SQL:
                r.fetchone.return_value=membership()
            elif sql==roster.NONMASTER_SAMPLE_SQL:
                r.fetchall.return_value=[]
            return r
        conn.execute.side_effect=execute
        with patch.object(roster.psycopg,"connect",return_value=conn) as c:
            out=roster.inspect("protected")
        self.assertFalse(out["historical_eligibility_date_by_date_verified"])
        self.assertEqual(out["database_writes"],0)
        self.assertIn("default_transaction_read_only=on",c.call_args.kwargs["options"])

class CorporateActionsTotalReturnSafetyTests(TestCase):
    def test_duplicate_economic_cash_events_do_not_certify_total_return(self):
        first=event()
        duplicate=event(eid="source_2")
        cap_change=event(kind="FACE_VALUE_CHANGE",eid="source_3",
                         ex_date=date(2026,4,13),factor=".25")
        cap_change["share_factor"]="4"
        other=event(market="twse",stock="6213",eid="twse_1",
                    verified=False,kind="OTHER",factor="1")
        out=actions.assess([first,duplicate,cap_change,other],masters(),
                           actual_event_count=4)
        self.assertEqual(out["original_corporate_action_records"],4)
        self.assertEqual(out["distinct_economic_events_by_factor"],3)
        self.assertEqual(out["duplicated_economic_source_rows"],1)
        self.assertEqual(out["market"]["tpex"]["stock_ids_with_verified_action"],1)
        self.assertEqual(out["cash_dividend_records_missing_explicit_cash_amount"],2)
        self.assertEqual(out["events_without_original_issuer_publication_vintage"],4)
        self.assertFalse(out["historic_true_total_return_labels_verified"])
        self.assertFalse(out["raw_price_only_ai_labels_may_be_promoted_to_total_return"])
        with self.assertRaises(PermissionError):
            actions.require_total_return_label_certification(out)

    def test_actual_adjustment_dedup_is_not_proof_of_dividend_cash_return(self):
        # A 100 -> 95 raw quote across ex-date looks -5% unadjusted;
        # applying a 0.95 reference factor to the prior close removes the
        # mechanical jump, but cash_amount is NULL so total-return is unproven.
        price=[{"trade_date":"2025-09-08","open":100,"high":101,
                "low":99,"close":100,"volume":1000},
               {"trade_date":"2025-09-09","open":95,"high":96,
                "low":94,"close":95,"volume":1000}]
        first=event()
        second=event(eid="same_day_new_raw_source_id")
        adjusted=adjust_bars(price,[first,second])
        self.assertAlmostEqual(adjusted[0]["close"],95)
        self.assertAlmostEqual(adjusted[1]["close"],95)
        self.assertNotAlmostEqual(price[0]["close"],adjusted[0]["close"])
        flags=actions.label_window_risk(entry_date=date(2025,9,8),
            exit_date=date(2025,9,9),events=[first,second])
        self.assertTrue(flags["crossed_any_incomplete_cash_dividend_amount"])
        self.assertEqual(flags["recorded_verified_action_rows_crossed"],2)
        self.assertFalse(flags["actual_adjusted_total_return_label_approved"])
        with self.assertRaises(ValueError):
            actions.label_window_risk(entry_date=date(2025,9,9),
                                      exit_date=date(2025,9,8),events=[first])

    def test_bad_factor_duplicate_id_and_missing_market_denominator_fail_closed(self):
        for invalid in ("NaN","Infinity","-1","0","garbage"):
            with self.subTest(factor=invalid):
                with self.assertRaises(ValueError):
                    actions.assess([event(factor=invalid)],masters(),
                                   actual_event_count=1)
        with self.assertRaises(ValueError):
            actions.assess([event(),event()],masters(),actual_event_count=2)
        with self.assertRaises(ValueError):
            actions.assess([event()],masters(),actual_event_count=2)
        with self.assertRaises(ValueError):
            actions.assess([event()],masters()[:1],actual_event_count=1)
        with self.assertRaises(ValueError):
            actions.assess([event()],masters(),actual_event_count=1001)

    def test_readonly_live_action_query_and_no_cron_or_unsafe_actions(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def query(sql,args=None):
            q=MagicMock()
            if sql==actions.EVENT_TOTAL_SQL:
                q.fetchone.return_value={"n":2}
            elif sql==actions.EVENT_SQL:
                q.fetchall.return_value=[event(),event(eid="source_2")]
            elif sql==actions.CURRENT_MASTER_SQL:
                q.fetchall.return_value=masters()
            return q
        conn.execute.side_effect=query
        with patch.object(actions.psycopg,"connect",return_value=conn) as c:
            report=actions.inspect("protected")
        self.assertEqual(report["duplicated_economic_source_rows"],1)
        self.assertTrue(report["database_read_only"])
        self.assertIn("default_transaction_read_only=on",c.call_args.kwargs["options"])
        wf=(ROOT/".github/workflows/tpex-five-year-free-safety-evidence.yml").read_text()
        self.assertIn("  workflow_run:",wf)
        self.assertIn("  push:",wf)
        self.assertIn("  workflow_dispatch:",wf)
        self.assertIn(".github/tpex-free-safety-evidence-20261121.txt",wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("--apply",wf)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",wf)
        for script in ("tpex_free_storage_stress.py",
                       "tpex_historical_roster_audit.py",
                       "audit_total_return_label_provenance.py"):
            self.assertIn(script,wf)
