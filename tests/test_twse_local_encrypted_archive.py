"""Local-only encrypted archive integrity, AES auth and fail-closed tests.

No actual Neon access or user archive creation in public GitHub CI.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import gzip
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts import twse_local_encrypted_archive as tool


def fake_row(day, sid):
    return {
        "market": "twse",
        "stock_id": sid,
        "trade_date": day,
        "open": Decimal("101.0000"),
        "high": Decimal("105.25"),
        "low": Decimal("100.005"),
        "close": Decimal("103.5000"),
        "volume": 112_345,
        "turnover": Decimal("11993788.000000"),
        "price_change": Decimal("-0.25000"),
        "transactions": 100,
        "source": tool.SOURCE,
        "retrieved_at": datetime(2026, 11, 20, 8, 30, 12, 123456,
                                 tzinfo=timezone.utc),
    }


class LocalEncryptedArchiveTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "twse-test.twseenc"
        self.key = secrets.token_hex(32)
        self.start = date(2026, 11, 19)
        self.end = date(2026, 11, 20)

    def _write(self, rows=None):
        if rows is None:
            rows = [fake_row(self.start, "1101"),
                    fake_row(self.start, "2330"),
                    fake_row(self.end, "1101")]
        return tool.encrypt_rows(rows, self.file, start=self.start,
                                 end=self.end, hex_key=self.key)

    def test_two_chunks_lossless_decimal_and_timestamp_and_no_plaintext(self):
        ids = [f"{i:04d}" for i in range(1000, 1710) if i != 1589]
        rows = [fake_row(self.start, sid) for sid in ids]
        created = self._write(rows)
        proof = tool.verify_archive(self.file, hex_key=self.key)
        self.assertEqual(created["rows"], len(rows))
        self.assertEqual(proof["sample_rows"], len(rows))
        self.assertGreaterEqual(proof["chunks"], 2)
        self.assertTrue(proof["archive_integrity_verified"])
        self.assertTrue(proof["all_decimal_values_and_retrieved_at_exactly_restored"])
        self.assertFalse(proof["delete_or_migrate_neon_authorized"])
        self.assertFalse(proof["independent_second_backup_verified"])
        encrypted = self.file.read_bytes()
        self.assertNotIn(b"11993788.000000", encrypted)
        from struct import unpack
        offset = len(tool.MAGIC)
        header_len = unpack(">I", encrypted[offset:offset+4])[0]
        ciphertext_only = encrypted[offset+4+header_len:]
        self.assertNotIn(b"2026-11-19", ciphertext_only)
        self.assertNotIn(b"11993788.000000", ciphertext_only)
        self.assertEqual(created["production_neon_deleted_rows"], 0)

    def test_wrong_key_and_tampering_refused(self):
        self._write()
        with self.assertRaises(Exception):
            tool.verify_archive(self.file, hex_key=secrets.token_hex(32))
        intact = self.file.read_bytes()
        self.file.write_bytes(intact[:-8])
        with self.assertRaises((ValueError, Exception)):
            tool.verify_archive(self.file, hex_key=self.key)
        self.file.write_bytes(intact[:-35] + bytes([intact[-35] ^ 0x01]) + intact[-34:])
        with self.assertRaises(Exception):
            tool.verify_archive(self.file, hex_key=self.key)
        self.file.write_bytes(intact + b"NOT-ALLOWED-EXTRA")
        with self.assertRaises(ValueError):
            tool.verify_archive(self.file, hex_key=self.key)

    def test_archive_can_never_overwrite(self):
        self._write()
        original = self.file.read_bytes()
        with self.assertRaises(FileExistsError):
            self._write()
        self.assertEqual(self.file.read_bytes(), original)

    def test_duplicate_and_wrong_date_fails_without_partial_file(self):
        with self.assertRaises(ValueError):
            self._write([fake_row(self.start, "2330"),
                         fake_row(self.start, "2330")])
        self.assertFalse(self.file.exists())
        with self.assertRaises(ValueError):
            self._write([fake_row(date(2020, 1, 1), "2330")])
        self.assertFalse(self.file.exists())
        with self.assertRaises(ValueError):
            self._write([fake_row(self.start, "1589")])
        self.assertFalse(self.file.exists())

    def test_export_is_forbidden_inside_public_git_checkout(self):
        base = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(ValueError, "outside git"):
            tool.encrypt_rows([fake_row(self.start, "2330")],
                              base / "DO-NOT-WRITE.twseenc",
                              start=self.start,end=self.end,hex_key=self.key)

    def test_strict_bounded_period_encryption_key_and_gzip_bomb(self):
        with self.assertRaises(ValueError):
            self._write([])
        with self.assertRaises(ValueError):
            tool.encrypt_rows([fake_row(self.start,"2330")],self.file,
                              start=date(2021, 1, 1),end=self.end,
                              hex_key=self.key)
        with self.assertRaises(ValueError):
            tool.encrypt_rows([fake_row(self.start,"2330")],self.file,
                              start=self.start,end=self.end,
                              hex_key="obviously-not-a-key")
        with self.assertRaises(ValueError):
            tool._gunzip_bounded(
                gzip.compress(b"A" * (tool.MAX_RAW_CHUNK_BYTES + 100),
                              compresslevel=9))
        self.assertFalse(self.file.exists())

    def test_query_mandatory_official_current_issuer_and_model_exclusion(self):
        q = tool.EXPORT_SQL
        self.assertIn("official_current_listed o", q)
        self.assertIn("model_stock_exclusions", q)
        self.assertIn("p.stock_id<>'1589'", q)
        self.assertIn("p.source='TWSE_MI_INDEX_ALLBUT0999'", q)
        self.assertIn("ORDER BY p.trade_date,p.stock_id", q)
        for prohibited in ("INSERT INTO", "UPDATE ", "DELETE FROM",
                           "DROP TABLE", "DROP INDEX", "TRUNCATE"):
            self.assertNotIn(prohibited, q.upper())
        self.assertLessEqual(tool.MAX_EXPORT_DAYS, 35)
        self.assertEqual(tool.ROWS_PER_CHUNK, 500)

    def test_encrypted_archive_is_not_a_backed_up_migration(self):
        self._write()
        verified = tool.verify_archive(self.file, hex_key=self.key)
        self.assertFalse(verified["delete_or_migrate_neon_authorized"])
        self.assertTrue(verified["data_was_never_restored_to_neon"])
        self.assertFalse(verified["line_modified"])
