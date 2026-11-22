"""Offline AES-GCM whole-market date reconciliation and no-duplicate plan tests.

No Neon credentials, official HTTP downloads, user keys or private archives.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import secrets
import unittest
from unittest.mock import patch

from scripts.twse_local_encrypted_archive import encrypt_rows
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_2021_22_archive_plan_readonly import plan
from tests.test_twse_stateless_2022_source_probe import rows


class AuthenticatedAESDateDedupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.key = secrets.token_hex(32)
        self.days = [date(2022, 1, 4), date(2022, 1, 5)]
        self.meta = {
            "active_twse": 1092,
            "exclusion_1589": 1,
            "database_bytes": 751689728,
            "official_receipt": datetime(2026, 11, 22, tzinfo=timezone.utc),
        }

    def make_bars(self, day, *, n=720, conflicting=False):
        result = rows(day, number=n)
        if conflicting:
            result[0]["close"] = Decimal("-1")
        # Existing real official 2330 anchor is required independently of
        # current-market source row count.
        result.append({**result[0], "stock_id": "2330"})
        for item in result:
            item["retrieved_at"] = datetime(2026, 11, 22, tzinfo=timezone.utc)
        return sorted(result, key=lambda x: x["stock_id"])

    def save(self, file, day, *, n=720, conflicting=False):
        path = self.p / file
        encrypt_rows(self.make_bars(day, n=n, conflicting=conflicting),
                     path, start=day, end=day, hex_key=self.key)
        return path

    def test_two_real_authenticated_days_cause_zero_repeat_gets(self):
        paths = [self.save("day1.twseenc",self.days[0]),
                 self.save("day2.twseenc",self.days[1])]
        proof = authenticated_archive_days(paths, hex_key=self.key,
                                           start=date(2022,1,1),end=date(2023,1,1))
        self.assertEqual(proof["days"], frozenset(self.days))
        self.assertEqual(proof["authenticated_private_files"], 2)
        self.assertEqual(proof["authenticated_private_source_rows"], 1442)
        self.assertTrue(proof["full_file_integrity_verified"])
        data = plan([(self.days[0],20,0,0),(self.days[1],20,0,0)],
                    self.meta,today=date(2026,11,23),
                    owner_aes_evidence=proof)
        self.assertEqual(data["sparse_unprocessed_days_to_independently_source_verify"],2)
        self.assertEqual(data["authenticated_existing_owner_aes_source_days_within_sparse_gaps"],2)
        self.assertEqual(data["remaining_sparse_days_without_authenticated_owner_aes"],0)
        self.assertEqual(data["bounded_private_archive_batch_count"],0)
        self.assertEqual(data["postgres_writes_performed"],0)
        self.assertEqual(data["line_messages_sent"],0)
        self.assertEqual(data["live_model_release"],"BLOCKED")

    def test_partial_authenticated_day_fails_instead_of_suppressing_get(self):
        path=self.save("partial.twseenc",self.days[0],n=200)
        with self.assertRaisesRegex(ValueError,"Insufficient"):
            authenticated_archive_days([path],hex_key=self.key,
                                      start=date(2022,1,1),end=date(2023,1,1))

    def test_tampered_ciphertext_and_invalid_key_fail_closed(self):
        path=self.save("tamper.twseenc",self.days[0])
        raw=bytearray(path.read_bytes())
        raw[-15]^=1
        path.write_bytes(raw)
        with self.assertRaises(Exception):
            authenticated_archive_days([path],hex_key=self.key,
                                      start=date(2022,1,1),end=date(2023,1,1))
        clean=self.save("clean.twseenc",self.days[1])
        with self.assertRaises(Exception):
            authenticated_archive_days([clean],hex_key=secrets.token_hex(32),
                                      start=date(2022,1,1),end=date(2023,1,1))

    def test_duplicate_aes_sources_fail_before_any_reuse(self):
        a=self.save("first.twseenc",self.days[0])
        b=self.save("repeat.twseenc",self.days[0])
        with self.assertRaisesRegex(ValueError,"Overlapping"):
            authenticated_archive_days([a,b],hex_key=self.key,
                                      start=date(2022,1,1),end=date(2023,1,1))
        with self.assertRaisesRegex(ValueError,"Repeated"):
            authenticated_archive_days([a,a],hex_key=self.key,
                                      start=date(2022,1,1),end=date(2023,1,1))

    def test_authenticated_out_of_window_file_not_counted_or_skipped_unchecked(self):
        other=date(2024,1,2)
        a=self.save("later.twseenc",other)
        proof=authenticated_archive_days([a],hex_key=self.key,
                                        start=date(2022,1,1),end=date(2023,1,1))
        self.assertFalse(proof["days"])
        self.assertEqual(proof["out_of_window_private_files_authenticated"],1)

    def test_invalid_evidence_or_unmatched_neon_anchor_blocks_false_completion(self):
        good=self.save("real.twseenc",self.days[0])
        proof=authenticated_archive_days([good],hex_key=self.key,
                                        start=date(2022,1,1),end=date(2023,1,1))
        with self.assertRaisesRegex(ValueError,"anchor"):
            plan([(self.days[1],20,0,0)],self.meta,today=date(2026,11,23),
                 owner_aes_evidence=proof)
        fake={**proof,"full_file_integrity_verified":False}
        with self.assertRaisesRegex(ValueError,"authenticated"):
            plan([(self.days[0],20,0,0)],self.meta,today=date(2026,11,23),
                 owner_aes_evidence=fake)

    def test_one_local_aes_day_leaves_only_other_day_for_preview(self):
        good=self.save("first.twseenc",self.days[0])
        proof=authenticated_archive_days([good],hex_key=self.key,
                                        start=date(2022,1,1),end=date(2023,1,1))
        result=plan([(self.days[0],20,0,0),(self.days[1],20,0,0)],
                    self.meta,today=date(2026,11,23),
                    owner_aes_evidence=proof)
        self.assertEqual(result["remaining_sparse_days_without_authenticated_owner_aes"],1)
        self.assertEqual(result["bounded_private_archive_batch_count"],1)
        self.assertEqual(result["batch_previews"][0]["start"],"2022-01-05")
        self.assertEqual(result["batch_previews"][0]["end"],"2022-01-05")


if __name__ == "__main__":
    unittest.main()
