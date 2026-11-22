"""Disposable localhost PostgreSQL AES-archive restore; never write Neon."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch

from scripts.twse_local_archive_postgres_restore_drill import (
    validate_disposable_target, drill, TEMP_CREATE, COPY_SQL,
)
from scripts.twse_local_encrypted_archive import encrypt_rows, verify_archive
from tests.test_twse_local_encrypted_archive import fake_row


URL = os.environ.get("STOCK_CI_RESTORE_URL")


class LocalOnlyRestoreSecurityTests(TestCase):
    def test_refuse_remote_and_overrides_before_any_connection(self):
        for url in (
            "", "postgresql://stock_ci_restore:pw@neon.tech:5432/stock_ci_restore",
            "postgresql://postgres:pw@localhost:5432/stock_ci_restore",
            "postgresql://stock_ci_restore:pw@localhost:5432/twstock",
            "postgresql://stock_ci_restore:pw@localhost:6543/stock_ci_restore",
            "postgresql://stock_ci_restore:pw@localhost:5432/stock_ci_restore?hostaddr=8.8.8.8",
            "postgresql:///stock_ci_restore",
            "postgresql://stock_ci_restore@localhost:5432/stock_ci_restore",
            "postgresql://stock_ci_restore:pw@localhost:5432/stock_ci_restore#unsafe",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_disposable_target(url)
        validate_disposable_target(
            "postgresql://stock_ci_restore:test@127.0.0.1:5432/stock_ci_restore"
        )

    def test_archive_corruption_rejected_before_connecting(self):
        with TemporaryDirectory() as td:
            file = Path(td) / "sample.twseenc"
            key = secrets.token_hex(32)
            first, last = date(2026,11,19),date(2026,11,20)
            encrypt_rows([fake_row(first,"1101"),fake_row(last,"2330")],
                         file,start=first,end=last,hex_key=key)
            file.write_bytes(file.read_bytes()[:-10])
            with patch("psycopg.connect") as connected:
                with self.assertRaises(Exception):
                    drill(file,hex_key=key,local_database_url=
                          "postgresql://stock_ci_restore:pw@127.0.0.1:5432/stock_ci_restore")
                connected.assert_not_called()

    def test_only_session_local_tables_and_no_production_sql(self):
        self.assertIn("CREATE TEMP TABLE",TEMP_CREATE)
        self.assertIn("ON COMMIT DROP",TEMP_CREATE)
        self.assertIn("pg_temp.",COPY_SQL)
        for forbidden in ("INSERT INTO public.", "UPDATE public.", "DELETE FROM public.",
                          "TRUNCATE public.", "DROP TABLE public."):
            self.assertNotIn(forbidden, TEMP_CREATE + COPY_SQL)


@skipUnless(URL, "Only disposable localhost PostgreSQL enables this test")
class RealDisposablePostgresRestoreTests(TestCase):
    def test_exact_numeric_timestamp_and_chunked_rows_restore_then_temp_drop(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "sample.twseenc"
            key = secrets.token_hex(32)
            first, last = date(2026,11,19), date(2026,11,20)
            stock_codes = [
                f"{i:04d}" for i in range(1000,1700) if i != 1589
            ][:550]
            rows = [fake_row(first,s) for s in stock_codes]
            for i,row in enumerate(rows):
                if i%11 == 0:
                    row["retrieved_at"] = datetime(
                        2026,11,20,16,35,12,123456,
                        tzinfo=timezone(timedelta(hours=8))
                    )
                if i%13 == 0:
                    row["close"] = Decimal("100.005000000")
            encrypt_rows(rows,path,start=first,end=last,hex_key=key)
            report = drill(path,hex_key=key,local_database_url=URL)
            self.assertEqual(report["verified_rows_restored_into_temporary_table"],
                             len(rows))
            self.assertTrue(report["exact_decimal_and_timezone_source_sha256_passed"])
            self.assertTrue(report["postgres_temp_table_dropped_at_transaction_commit"])
            self.assertEqual(report["persistent_database_rows_written"],0)
            self.assertFalse(report["neon_database_connected"])
            self.assertFalse(report["real_owner_archive_restoration_tested"])
            self.assertFalse(report["neon_deletion_or_migration_approved"])
            self.assertFalse(report["live_trading_approved"])

            import psycopg
            with psycopg.connect(URL) as conn:
                n=conn.execute("SELECT to_regclass('pg_temp.twse_archive_restore_drill')").fetchone()
                self.assertIsNone(n[0])
                table=conn.execute("""
                    SELECT COUNT(*) FROM pg_tables
                    WHERE schemaname='public' AND tablename='twse_archive_restore_drill'
                """).fetchone()[0]
                self.assertEqual(table,0)

    def test_cannot_write_corrupt_archive_into_disposable_database(self):
        with TemporaryDirectory() as td:
            path=Path(td)/"corrupt.twseenc"
            key=secrets.token_hex(32)
            encrypt_rows([fake_row(date(2026,11,20),"2330")],
                         path,start=date(2026,11,20),
                         end=date(2026,11,20),hex_key=key)
            valid=path.read_bytes()
            path.write_bytes(valid[:-7])
            with self.assertRaises(Exception):
                drill(path,hex_key=key,local_database_url=URL)
