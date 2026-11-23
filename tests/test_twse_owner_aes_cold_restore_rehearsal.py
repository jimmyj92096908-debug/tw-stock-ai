"""Synthetic offline authenticated restoration tests; NEVER use owner files or Neon."""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest

from scripts.twse_local_encrypted_archive import encrypt_rows, verify_archive, SOURCE
from scripts.twse_owner_aes_cold_restore_rehearsal import rehearse


def row(day, stock):
    return {
        "market": "twse", "stock_id": stock, "trade_date": day,
        "open": Decimal("100.2500"), "high": Decimal("103.0000"),
        "low": Decimal("99.5000"), "close": Decimal("101.2000"),
        "volume": 100_000, "turnover": Decimal("10120000.00"),
        "price_change": Decimal("0.9500"), "transactions": 10,
        "source": SOURCE,
        "retrieved_at": datetime(2026, 11, 20, 8, 30, 12, tzinfo=timezone.utc),
    }


class ColdRestoreRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source21 = self.base / "source21"
        self.source22 = self.base / "source22"
        self.source21.mkdir()
        self.source22.mkdir()
        self.key = secrets.token_hex(32)
        self.target = self.base / "restored-new"
        # A genuinely authenticated source market must have many real-like
        # rows and an anchor for 2330, not a one-stock canary.
        stocks = sorted([f"{n:04d}" for n in range(1100, 1660)
                         if n != 1589] + ["2330"])
        for source, dt in ((self.source21, date(2021, 11, 23)),
                           (self.source22, date(2022, 1, 3))):
            encrypt_rows((row(dt, sid) for sid in stocks),
                         source / (dt.isoformat() + ".twseenc"),
                         start=dt, end=dt, hex_key=self.key)

    def _rehearse(self, key=None, path=None):
        # Production CLI never exposes the expected-source-day overrides.
        return rehearse(self.source21, self.source22, path or self.target,
                        hex_key=key or self.key, expected_source_days=(1, 1))

    def test_mirrored_copy_is_authenticated_and_exactly_recoverable(self):
        result = self._rehearse()
        self.assertTrue(result["all_chunks_aes_gcm_authenticated"])
        self.assertTrue(result["original_vs_restored_ciphertext_sha256_all_equal"])
        self.assertTrue(result["original_vs_restored_canonical_OHLCV_rows_all_equal"])
        self.assertEqual(result["authenticated_2021_source_days"], 1)
        self.assertEqual(result["authenticated_2022_aes_source_days"], 1)
        self.assertEqual(result["source_archives_copied_and_authenticated"], 2)
        self.assertFalse(result["source_copy_proven_to_be_on_separate_physical_media"])
        self.assertFalse(result["restore_into_neon_tested"])
        self.assertFalse(result["authorized_to_delete_or_rewrite_neon_data"])
        self.assertFalse(result["safe_to_run_production_backfill"])
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["model_release"], "BLOCKED")
        receipt = self.target / "private-aes-cold-restore-receipt.json"
        self.assertTrue(receipt.is_file())
        for year in ("2021", "2022"):
            restored = list((self.target / year).glob("*.twseenc"))
            self.assertEqual(len(restored), 1)
            self.assertTrue(verify_archive(restored[0], hex_key=self.key)["archive_integrity_verified"])
        # A repeat must fail, not overwrite the successfully restored copy.
        previous = receipt.read_bytes()
        with self.assertRaises(ValueError):
            self._rehearse()
        self.assertEqual(receipt.read_bytes(), previous)

    def test_wrong_key_rejected_before_any_copy(self):
        with self.assertRaises(Exception):
            self._rehearse(key=secrets.token_hex(32))
        self.assertFalse(self.target.exists())

    def test_tampered_source_rejected_without_backup(self):
        archive = next(self.source22.glob("*.twseenc"))
        data = archive.read_bytes()
        archive.write_bytes(data[:-33] + bytes([data[-33] ^ 1]) + data[-32:])
        with self.assertRaises(Exception):
            self._rehearse()
        self.assertFalse(self.target.exists())

    def test_never_nest_restore_under_original_archive(self):
        with self.assertRaises(ValueError):
            self._rehearse(path=self.source21 / "bad-subdir")
        self.assertFalse((self.source21 / "bad-subdir").exists())

    def test_original_files_remain_unchanged_after_rehearsal(self):
        before = {p: p.read_bytes() for p in
                  list(self.source21.glob("*.twseenc")) +
                  list(self.source22.glob("*.twseenc"))}
        self._rehearse()
        self.assertEqual(before, {p: p.read_bytes() for p in before})


if __name__ == "__main__":
    unittest.main()
