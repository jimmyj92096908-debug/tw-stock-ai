"""Honest Neon network quota and research precommit immutability tests."""
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch
import json

from scripts import neon_free_meter_guard as quota
from scripts import prospective_forward_maturity_readonly as follow

ROOT=Path(__file__).resolve().parents[1]

def api_usage(t=486363304):
    return {"id":quota.PROJECT_ID,"data_transfer_bytes":t,
            "compute_time_seconds":36695,
            "consumption_period_end":"2026-12-01T00:00:00Z"}

class MeterTests(TestCase):
    def test_actual_neon_api_usage_and_distinct_storage_thresholds(self):
        x=quota.assess(db_bytes=490766336,usage=api_usage())
        self.assertEqual(x["network_transfer_status"],"NORMAL")
        self.assertTrue(x["additional_data_intensive_jobs_authorized"])
        self.assertEqual(x["project_network_transfer_bytes"],486363304)
        self.assertFalse(x["compute_CU_hours_derived_without_compute_size"])
        self.assertEqual(quota.assess(db_bytes=700000000,usage=api_usage())[
            "database_status"],"WARNING")
        self.assertEqual(quota.assess(db_bytes=800000000,usage=api_usage())[
            "database_status"],"STOP")
        self.assertEqual(quota.assess(db_bytes=500000000,usage=api_usage(4000000000))[
            "network_transfer_status"],"WARNING")
        self.assertFalse(quota.assess(db_bytes=500000000,usage=api_usage(4500000000))[
            "additional_data_intensive_jobs_authorized"])

    def test_missing_or_mismatched_neon_api_data_is_never_safe(self):
        unknown=quota.assess(db_bytes=490000000)
        self.assertEqual(unknown["network_transfer_status"],"UNAVAILABLE")
        self.assertIsNone(unknown["project_network_transfer_bytes"])
        self.assertFalse(unknown["additional_data_intensive_jobs_authorized"])
        for bad in (
            {"id":"different-project","data_transfer_bytes":400,
             "compute_time_seconds":90,"consumption_period_end":"2026-12-01"},
            api_usage(t=-2),api_usage(t=True),
            {**api_usage(),"compute_time_seconds":None}
        ):
            with self.assertRaises(ValueError):
                quota.assess(db_bytes=300000000,usage=bad)

    def test_no_secret_in_failure_or_persisted_report(self):
        response=MagicMock()
        response.__enter__.return_value=BytesIO(
            json.dumps({"project":api_usage()}).encode())
        with patch.object(quota,"urlopen",return_value=response) as opener:
            actual=quota.fetch_meter("dont-echo-this-token",opener=opener)
        self.assertEqual(actual["id"],quota.PROJECT_ID)
        req=opener.call_args.args[0]
        self.assertIn("dont-echo-this-token",req.get_header("Authorization"))
        conn=MagicMock();conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={"bytes":490000000}
        with patch.object(quota.psycopg,"connect",return_value=conn),\
             patch.object(quota,"fetch_meter",side_effect=Exception("dont-echo-this-token")):
            report=quota.run("secret-neon-url","dont-echo-this-token")
            self.assertEqual(report["network_transfer_status"],"UNAVAILABLE")
            self.assertNotIn("dont-echo-this-token",json.dumps(report))
            with self.assertRaises(RuntimeError):
                quota.run("secret-neon-url","dont-echo-this-token",require_network=True)

    def test_all_meter_sql_and_prospective_workflow_fail_closed(self):
        self.assertIn("pg_database_size",quota.SIZE_SQL)
        wf=(ROOT/".github/workflows/prospective-free-safe-daily.yml").read_text()
        for marker in (
            "Official Taiwan Market Daily Snapshot (Authorized)",
            "github.event.workflow_run.event == 'schedule'",
            "neon_free_meter_guard.py",
            "freeze_prospective_research.py",
            "prospective_forward_maturity_readonly.py",
            "composite-score-after-market-refresh",
            "inputs.apply == true",
        ):
            self.assertIn(marker,wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN",wf)
        self.assertIn("STOCK_FORWARD_RESEARCH_FREEZE_WRITE",wf)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",wf)

class ProspectiveFollowupTests(TestCase):
    def test_no_mature_pristine_cohort_can_be_backfilled(self):
        conn=MagicMock();conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={
            "mature_candidate":None,"last_market_day":date(2026,11,20)}
        with patch.object(follow.psycopg,"connect",return_value=conn) as con,\
             patch.object(follow,"examine") as calc:
            x=follow.check("existing-protected-dsn")
        self.assertEqual(x["status"],"NO_OLDER_PRECOMMITTED_COHORT_AVAILABLE")
        self.assertFalse(x["matured_forward_alpha_proven"])
        self.assertFalse(x["LINE_or_trading_enabled"])
        self.assertEqual(x["database_writes"],0)
        calc.assert_not_called()
        self.assertIn("default_transaction_read_only=on",con.call_args.kwargs["options"])

    def test_only_truly_previous_precommitted_date_audited(self):
        conn=MagicMock();conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={
            "mature_candidate":date(2026,11,20),"last_market_day":date(2026,12,2)}
        with patch.object(follow.psycopg,"connect",return_value=conn),\
             patch.object(follow,"examine",return_value={
                "status":"PENDING_WHOLE_COHORT_MATURITY",
                "live_trading_approved":False}) as audit:
            result=follow.check("protected")
        audit.assert_called_once_with("protected",model_version="tw-factor-ridge-1",
            signal_date=date(2026,11,20),cutoff=date(2026,12,2))
        self.assertFalse(result["matured_forward_alpha_proven"])
        self.assertFalse(result["LINE_or_trading_enabled"])
