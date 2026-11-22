"""Two private AES archive copies are authenticated; missing dates remain blocked."""
from datetime import date
from pathlib import Path
import os
import secrets
import shutil
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.twse_local_archive_custody_audit import (
    review_manifest, verify_pair, MAX_ARCHIVES,
)
from scripts.twse_local_encrypted_archive import encrypt_rows
from tests.test_twse_local_encrypted_archive import fake_row


class TWSEPrivateArchiveCustodyTests(TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        (self.root / "primary").mkdir()
        (self.root / "backup").mkdir()
        self.key = secrets.token_hex(32)

    def archive_pair(self, filename, first, last):
        p = self.root / "primary" / (filename + ".twseenc")
        b = self.root / "backup" / (filename + ".twseenc")
        encrypt_rows([fake_row(first,"1101"),fake_row(last,"2330")],
                     p,start=first,end=last,hex_key=self.key)
        shutil.copy2(p,b)
        return p,b

    def test_two_copies_and_contiguous_multi_periods_never_permit_migration(self):
        a,b = self.archive_pair("first",date(2026,11,19),date(2026,11,20))
        c,d = self.archive_pair("second",date(2026,11,21),date(2026,11,22))
        result = review_manifest({
            "start":"2026-11-19","end":"2026-11-22",
            "pairs":[{"primary":str(a),"backup":str(b)},
                     {"primary":str(c),"backup":str(d)}],
        },hex_key=self.key)
        self.assertEqual(result["archive_pairs_verified"],2)
        self.assertEqual(result["total_archived_rows"],4)
        self.assertTrue(result["consecutive_calendar_window_coverage"])
        self.assertTrue(result["distinct_copies_authenticated_and_equal"])
        self.assertFalse(result["physical_independence_verified"])
        self.assertFalse(result["all_five_year_trading_days_archived"])
        self.assertFalse(result["real_source_row_count_and_day_ledger_reconciled"])
        self.assertFalse(result["neon_deletion_or_migration_approved"])
        self.assertEqual(result["neon_rows_changed"],0)
        self.assertFalse(result["line_modified"])
        self.assertNotIn("primary",result)
        self.assertNotIn("backup",result)

    def test_missing_calendar_span_cannot_claim_complete(self):
        a,b = self.archive_pair("first",date(2026,11,19),date(2026,11,19))
        c,d = self.archive_pair("second",date(2026,11,21),date(2026,11,22))
        result = review_manifest({
            "start":"2026-11-19","end":"2026-11-22",
            "pairs":[{"primary":str(a),"backup":str(b)},
                     {"primary":str(c),"backup":str(d)}],
        },hex_key=self.key)
        self.assertFalse(result["consecutive_calendar_window_coverage"])
        self.assertFalse(result["all_five_year_trading_days_archived"])

    def test_reject_same_file_hardlink_wrong_key_and_corrupt_copy(self):
        a,b = self.archive_pair("one",date(2026,11,19),date(2026,11,20))
        with self.assertRaisesRegex(ValueError,"not be the original"):
            verify_pair(a,a,hex_key=self.key)
        alias=self.root / "backup" / "hardlink.twseenc"
        os.link(a,alias)
        with self.assertRaises(ValueError):
            verify_pair(a,alias,hex_key=self.key)
        with self.assertRaises(Exception):
            verify_pair(a,b,hex_key=secrets.token_hex(32))
        b.write_bytes(b.read_bytes()[:-3])
        with self.assertRaises(Exception):
            verify_pair(a,b,hex_key=self.key)

    def test_reject_overlap_out_of_range_or_unsorted_manifest(self):
        a,b=self.archive_pair("first",date(2026,11,19),date(2026,11,20))
        c,d=self.archive_pair("second",date(2026,11,20),date(2026,11,21))
        for plan in (
            {"start":"2026-11-19","end":"2026-11-22",
             "pairs":[{"primary":str(a),"backup":str(b)},
                      {"primary":str(c),"backup":str(d)}]},
            {"start":"2026-11-20","end":"2026-11-22",
             "pairs":[{"primary":str(a),"backup":str(b)}]},
            {"start":"2026-11-19","end":"2026-11-22",
             "pairs":[{"primary":str(c),"backup":str(d)},
                      {"primary":str(a),"backup":str(b)}]},
        ):
            with self.assertRaises(ValueError):
                review_manifest(plan,hex_key=self.key)

    def test_invalid_manifest_cannot_bypass_aes(self):
        with self.assertRaises(ValueError):
            review_manifest({"start":"2026-11-19","end":"2026-11-22",
                             "pairs":[]},hex_key=self.key)
        with self.assertRaises(ValueError):
            review_manifest({"start":"2026-11-19","end":"2026-11-22",
                             "pairs":[{"primary":"x"}]},hex_key=self.key)
        self.assertLessEqual(MAX_ARCHIVES,72)
