"""No-write archive/source parity, exact numeric and synthetic PG cursor tests."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import secrets
import shutil
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts.twse_local_archive_source_reconcile import (
    canonical_source_digest, reconcile_archive_set, EXPORT_SQL,
)
from scripts.twse_local_encrypted_archive import encrypt_rows, verify_archive
from tests.test_twse_local_encrypted_archive import fake_row


class SourceReconciliationTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.primary=self.root/"local.twseenc"
        self.secondary=self.root/"copy.twseenc"
        self.key=secrets.token_hex(32)
        self.first=date(2026,11,19)
        self.last=date(2026,11,20)
        self.rows=[fake_row(self.first,"1101"),
                   fake_row(self.first,"2330"),
                   fake_row(self.last,"1101")]
        encrypt_rows(self.rows,self.primary,start=self.first,
                     end=self.last,hex_key=self.key)
        shutil.copy2(self.primary,self.secondary)
        self.manifest={
            "start":"2026-11-19","end":"2026-11-20",
            "pairs":[{"primary":str(self.primary),"backup":str(self.secondary)}],
        }

    def connection(self, rows):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=MagicMock()
        cur.__enter__.return_value=cur
        cur.fetchmany.side_effect=[rows,[]]
        conn.cursor.return_value=cur
        return conn,cur

    def test_exact_live_pg_stream_reconciles_both_authenticated_archives(self):
        expected=verify_archive(self.primary,hex_key=self.key)
        count,digest=canonical_source_digest(self.rows,start=self.first,end=self.last)
        self.assertEqual(count,expected["sample_rows"])
        self.assertEqual(digest,expected["canonical_rows_sha256"])
        conn,cur=self.connection(self.rows)
        with patch("psycopg.connect",return_value=conn) as connected:
            report=reconcile_archive_set(
                self.manifest,database_url="postgresql://fake",
                hex_key=self.key,
            )
        self.assertTrue(report["all_archived_rows_matched_single_readonly_neon_snapshot"])
        self.assertEqual(report["archive_rows_reconciled_to_live_source"],3)
        self.assertTrue(report["consecutive_calendar_window_coverage"])
        self.assertFalse(report["approved_for_neon_deletion"])
        self.assertFalse(report["actual_independent_key_recovery_and_physical_backup_proven"])
        self.assertFalse(report["isolated_database_restore_test_passed"])
        self.assertFalse(report["approved_for_model_trading"])
        self.assertEqual(report["neon_database_writes"],0)
        self.assertFalse(report["line_modified"])
        self.assertIn("default_transaction_read_only=on",connected.call_args.kwargs["options"])
        self.assertEqual(conn.execute.call_args_list[0].args[0],
                         "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cur.execute.assert_called_once_with(
            EXPORT_SQL,{"start":self.first,"end":self.last}
        )
        self.assertNotIn("primary",report)
        self.assertNotIn("backup",report)

    def test_missing_or_changed_live_neon_row_never_claimed_archived(self):
        for live in (
            self.rows[:-1],
            [dict(self.rows[0],close=Decimal("777.2500"))]+self.rows[1:],
        ):
            conn,_=self.connection(live)
            with patch("psycopg.connect",return_value=conn):
                with self.assertRaisesRegex(ValueError,"source and"):
                    reconcile_archive_set(
                        self.manifest,database_url="fake",hex_key=self.key
                    )

    def test_authentication_failure_before_connecting_to_neon(self):
        self.secondary.write_bytes(self.secondary.read_bytes()[:-30])
        with patch("psycopg.connect") as connected:
            with self.assertRaises(Exception):
                reconcile_archive_set(self.manifest,database_url="fake",
                                      hex_key=self.key)
            connected.assert_not_called()

    def test_canonical_digest_rejects_missing_dates_1589_and_out_of_order(self):
        cases=[
            [fake_row(self.first,"1589")],
            [fake_row(date(2026,11,18),"2330")],
            [self.rows[1],self.rows[0]],
            [self.rows[0],self.rows[0]],
        ]
        for rows in cases:
            with self.assertRaises(ValueError):
                canonical_source_digest(rows,start=self.first,end=self.last)

    def test_source_sql_cannot_modify_production_or_include_delisted(self):
        self.assertIn("official_current_listed o",EXPORT_SQL)
        self.assertIn("model_stock_exclusions",EXPORT_SQL)
        self.assertIn("p.stock_id<>'1589'",EXPORT_SQL)
        self.assertIn("ORDER BY p.trade_date,p.stock_id",EXPORT_SQL)
        for token in ("INSERT INTO","DELETE FROM","UPDATE ","DROP TABLE","TRUNCATE"):
            self.assertNotIn(token,EXPORT_SQL.upper())
