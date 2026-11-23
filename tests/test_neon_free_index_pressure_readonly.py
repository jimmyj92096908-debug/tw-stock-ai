"""Synthetic-only five-table Neon Free metadata source and index safety."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from scripts import neon_free_index_pressure_readonly as m

CAPTURED = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)
RESET = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
REAL_READONLY_BYTES = 753_147_904


def receipts():
    meta = {
        "database_bytes": REAL_READONLY_BYTES,
        "observed_at": CAPTURED,
        "index_stat_reset_at": RESET,
    }
    tables = [
        ["daily_prices", 506331136, 290635776, 215588864, 2014549, 178],
        ["daily_adjusted_prices", 70336512, 42696704, 27590656, 278646, 23875],
        ["daily_technicals", 57868288, 41345024, 16474112, 278646, 27392],
        ["daily_smc", 52174848, 24559616, 27574272, 278646, 22786],
        ["daily_composite_scores", 42958848, 38133760, 4775936, 39290, 4760],
    ]
    rows = [dict(zip(
        ("table_name","table_total_bytes","heap_bytes","index_bytes",
         "estimated_live_rows","estimated_dead_rows"),r
    )) for r in tables]
    indexes = [
        ("daily_prices", "daily_prices_pkey", 107323392, 4307144),
        ("daily_prices", "idx_daily_prices_stock_date", 89767936, 1372889),
        ("daily_prices", "idx_daily_prices_date", 18497536, 18341),
        ("daily_adjusted_prices", "idx_daily_adjusted_prices_stock_date", 14581760, 776678),
        ("daily_adjusted_prices", "daily_adjusted_prices_pkey", 13008896, 1333865),
        ("daily_technicals", "daily_technicals_pkey", 13082624, 4760964),
        ("daily_technicals", "idx_daily_technicals_date", 3391488, 9589),
        ("daily_smc", "idx_daily_smc_stock_date", 14524416, 1435691),
        ("daily_smc", "daily_smc_pkey", 13049856, 994996),
        ("daily_composite_scores", "daily_composite_scores_pkey", 2514944, 159792),
        ("daily_composite_scores", "idx_daily_composite_scores_stock_date", 2260992, 712934),
    ]
    idx = [
        dict(zip(("table_name","index_name","index_bytes","index_scans"),row))
        for row in indexes
    ]
    return meta, rows, idx


class IndexPressureCatalogAuditTests(unittest.TestCase):
    def test_readonly_five_table_receipt_blocks_new_paid_storage_or_ddl(self):
        report=m.assess(*receipts())
        self.assertEqual(report["scope"],m.SCOPE)
        self.assertEqual(report["database_bytes_from_pg_database_size"],REAL_READONLY_BYTES)
        self.assertEqual(report["storage_workflow_preflight_status"],"ABSTAIN_STORAGE_WARN")
        self.assertEqual(report["conservative_free_workflow_warning_bytes"],650_000_000)
        self.assertEqual(report["conservative_production_hard_stop_bytes"],800_000_000)
        self.assertTrue(report["existing_650mb_free_gate_blocks_expensive_research"])
        self.assertTrue(report["database_bytes_below_hard_stop"])
        self.assertEqual(report["major_table_count"],5)
        self.assertEqual(report["all_inspected_index_count"],11)
        self.assertEqual(report["tables"]["daily_prices"]["table_index_bytes"],215588864)
        self.assertEqual(report["tables"]["daily_prices"]["table_total_bytes"],506331136)
        self.assertFalse(report["index_scan_stats_prove_index_safe_to_drop"])
        self.assertFalse(report["dead_tuple_counts_prove_reclaimable_disk_bytes"])
        self.assertEqual(report["indexes_approved_to_remove_or_rebuild"],[])
        self.assertFalse(report["production_price_backfill_approved"])
        self.assertFalse(report["production_index_ddl_approved"])
        self.assertFalse(report["neon_billing_quota_verified_by_this_script"])
        self.assertFalse(report["historical_stock_point_in_time_universe_verified"])
        self.assertFalse(report["owner_aes_and_neon_five_year_per_stock_coverage_completed_here"])
        self.assertEqual(report["source_price_rows_or_private_aes_read"],0)
        self.assertEqual(report["model_release"],"BLOCKED")
        self.assertEqual(report["neon_writes"],0)
        self.assertEqual(report["line_messages_sent"],0)
        self.assertFalse(report["additional_paid_services_used"])
        self.assertTrue(all(x["zero_scans_does_not_authorize_deletion"]
                            for x in report["indexes"]))

    def test_smaller_database_still_does_not_authorize_bulk_backfill(self):
        meta,table,idx=receipts()
        meta["database_bytes"]=sum(r["table_total_bytes"] for r in table)+1
        # Total already >650MB; test strictly smaller fixture with scaled
        # data, retaining physical accounting.
        for row in table:
            row["table_total_bytes"]//=4
            row["heap_bytes"]//=4
            row["index_bytes"]//=4
        for row in idx:
            row["index_bytes"]//=4
        # Integer rounding can make per-index sum differ; replace each
        # table's claimed index_bytes with the observed summed index sizes.
        for row in table:
            row["index_bytes"]=sum(i["index_bytes"] for i in idx
                                  if i["table_name"]==row["table_name"])
            row["table_total_bytes"]=row["heap_bytes"]+row["index_bytes"]+65536
        meta["database_bytes"]=sum(r["table_total_bytes"] for r in table)+1
        r=m.assess(meta,table,idx)
        self.assertEqual(r["storage_workflow_preflight_status"],
                         "BELOW_WARN_READONLY_OBSERVATION_ONLY")
        self.assertFalse(r["existing_650mb_free_gate_blocks_expensive_research"])
        self.assertFalse(r["production_price_backfill_approved"])
        self.assertFalse(r["production_index_ddl_approved"])

    def test_zero_index_scan_counter_is_not_deletion_permission(self):
        meta,table,idx=receipts()
        for i in idx:
            i["index_scans"]=0
        r=m.assess(meta,table,idx)
        self.assertFalse(r["index_scan_stats_prove_index_safe_to_drop"])
        self.assertEqual(r["indexes_approved_to_remove_or_rebuild"],[])
        self.assertTrue(all(i[
            "index_scan_count_since_stats_reset_not_lifetime_use"]==0
            for i in r["indexes"]))

    def test_fail_closed_on_missing_index_corrupt_bytes_or_repeated_catalog_row(self):
        mutations = (
            lambda m,t,i: i.pop(),
            lambda m,t,i: i[0].update({"index_name":i[1]["index_name"]}),
            lambda m,t,i: i[0].update({"index_scans":-1}),
            lambda m,t,i: i[0].update({"index_bytes":0}),
            lambda m,t,i: i[0].update({"table_name":"1589"}),
            lambda m,t,i: t[0].update({"table_name":"daily_smc"}),
            lambda m,t,i: t[0].update({"index_bytes":1}),
            lambda m,t,i: t[0].update({"estimated_dead_rows":-1}),
            lambda m,t,i: t[0].update({"table_total_bytes":1}),
            lambda m,t,i: m.update({"database_bytes":1}),
            lambda m,t,i: m.update({"database_bytes":True}),
            lambda m,t,i: m.update({"observed_at":"2026-11-24"}),
            lambda m,t,i: m.update({"index_stat_reset_at":"unverified"}),
        )
        for mutate in mutations:
            meta,table,idx=receipts()
            mutate(meta,table,idx)
            with self.subTest(fn=str(mutate)),self.assertRaises(ValueError):
                m.assess(meta,table,idx)
        meta,table,idx=receipts()
        meta["index_stat_reset_at"]=None
        r=m.assess(meta,table,idx)
        self.assertIsNone(r["index_scan_statistics_reset_at_utc_or_unknown"])

    def test_readonly_db_uses_catalog_only_four_commands_and_bounded_indexes(self):
        meta,table,idx=receipts()
        connection=MagicMock()
        connection.__enter__.return_value=connection
        connection.transaction.return_value.__enter__.return_value=connection
        cur=MagicMock()
        connection.cursor.return_value.__enter__.return_value=cur
        cur.fetchone.return_value=meta
        cur.fetchall.side_effect=[table,idx]
        with patch.object(m.psycopg,"connect",return_value=connection) as connect:
            r=m.capture(database_url="protected-not-logged")
        self.assertEqual(r["neon_writes"],0)
        connect.assert_called_once()
        self.assertEqual(connect.call_args.kwargs["options"],
                         "-c default_transaction_read_only=on")
        self.assertEqual(connect.call_args.kwargs["autocommit"],True)
        sql=[call.args[0] for call in cur.execute.call_args_list]
        self.assertEqual(sql,[
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
            "SET LOCAL statement_timeout = '6000ms'",
            m.HEAD_SQL,m.TABLE_SQL,m.INDEX_SQL
        ])
        self.assertEqual(cur.execute.call_args_list[-1].args[1],
                         (list(m.TABLES),))
        self.assertEqual(cur.execute.call_args_list[-2].args[1],
                         (list(m.TABLES),))
        self.assertIn("LIMIT 41",m.INDEX_SQL)
        self.assertNotIn("daily_prices p", " ".join(sql))
        self.assertNotIn("EXPLAIN ANALYZE", " ".join(sql))
        self.assertNotIn("INSERT INTO", " ".join(sql))
        self.assertNotIn("DELETE FROM", " ".join(sql))
        self.assertNotIn("DROP INDEX", " ".join(sql))

    def test_private_result_created_once_and_database_failures_are_sanitized(self):
        with TemporaryDirectory() as folder:
            dest=Path(folder)/"read-only-index-pressure.json"
            mod="scripts.neon_free_index_pressure_readonly"
            with patch(mod+"._private_file",
                       side_effect=lambda p,should_exist:Path(p)),\
                 patch(mod+".capture",
                       return_value=m.assess(*receipts())):
                m.run_owner(database_url="credential",out=dest)
                report=json.loads(dest.read_text(encoding="utf-8"))
                self.assertEqual(report["model_release"],"BLOCKED")
                original=dest.read_bytes()
                with self.assertRaises(m.AuditError) as caught:
                    m.run_owner(database_url="credential",out=dest)
                self.assertEqual(caught.exception.stage,"PRIVATE_REPORT_WRITE")
                self.assertEqual(original,dest.read_bytes())
        secret="postgresql://secret:secret-password@neon.hidden"
        with patch.object(m.psycopg,"connect",side_effect=ValueError(secret)):
            with self.assertRaises(m.AuditError) as caught:
                m._phase("READONLY_CATALOG",m.capture,database_url=secret)
        self.assertEqual(caught.exception.stage,"READONLY_CATALOG")
        self.assertNotIn(secret,str(caught.exception))
        self.assertNotIn(secret,m.safe_error(secret))


if __name__=="__main__":
    unittest.main()
