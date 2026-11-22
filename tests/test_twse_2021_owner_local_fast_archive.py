"""No-secret regression tests for restartable owner-private 2021 AES campaign."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import secrets
from unittest import TestCase

from scripts import twse_2021_owner_local_fast_archive as m


class OwnerOneCommandArchiveTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest=Path(self.temp.name)
        self.key=secrets.token_hex(32)
        self.today=date(2026,11,23)

    def test_28_day_source_dates_partition_four_local_aes_files(self):
        batches,count=m.plan_private_batches(frozenset(),today=self.today)
        self.assertEqual(count,28)
        self.assertEqual([len(batch) for batch in batches],[6,8,8,6])
        self.assertTrue(all(b[0].month==b[-1].month and len(b)<=8 for b in batches))
        self.assertEqual(tuple(day for b in batches for day in b),m.ALL_2021_DAYS)

    def test_authenticated_private_day_is_skipped_before_repeated_get(self):
        prior=frozenset({date(2021,11,23),date(2021,12,7)})
        batches,eligible=m.plan_private_batches(prior,today=self.today)
        flattened=[d for batch in batches for d in batch]
        self.assertEqual(eligible,28)
        self.assertEqual(len(flattened),26)
        self.assertTrue(prior.isdisjoint(flattened))
        self.assertTrue(all(len(batch)<=8 for batch in batches))
        # An archived middle day must split the batch so the separate Neon
        # preflight never fetches an already-authenticated private source day.
        self.assertFalse(any(batch[0]<date(2021,12,7)<batch[-1] for batch in batches))

    def test_full_one_command_run_with_mock_official_http_no_neon_writes(self):
        calls,pauses,filenames=[],[],[]
        planned,_=m.plan_private_batches(frozenset(),today=self.today)
        def preflight(db,*,start,end,today):
            batch=next(b for b in planned if b[0]==start)
            return list(batch),{("twse",str(i)) for i in range(1100,1810)}
        def prepare(db,*,start,end,archive_path,manifest_path,object_key,
                    hex_key,fetcher,today):
            dates=next(b for b in planned if b[0]==start)
            self.assertTrue(str(object_key).startswith("market=twse/year=2021/"))
            self.assertEqual(hex_key,self.key)
            filenames.append((archive_path,manifest_path))
            for d in dates:
                fetcher(d)
            return {
                "actual_official_session_dates":[d.isoformat() for d in dates],
                "encrypted_source_rows":700*len(dates),
                "production_postgres_rows_written":0,
                "line_messages_sent":0,
            }
        report=m.run_local("postgresql://fake",archive_dir=self.dest,
                           hex_key=self.key,today=self.today,
                           preflight_fn=preflight,prepare=prepare,
                           fetcher=lambda day:calls.append(day),
                           sleeper=pauses.append)
        self.assertEqual(calls,list(m.ALL_2021_DAYS))
        self.assertEqual(pauses,[4.0]*27)
        self.assertEqual(len(filenames),4)
        self.assertEqual(report["new_2021_source_days_encrypted_this_run"],28)
        self.assertEqual(report["new_encrypted_official_source_rows"],19600)
        self.assertEqual(report["remaining_unarchived_known_2021_source_days"],0)
        self.assertEqual(report["neon_source_and_derived_rows_written"],0)
        self.assertEqual(report["line_messages_sent"],0)
        self.assertFalse(report["live_model_release_approved"])
        self.assertNotIn(self.key,json.dumps(report))
        self.assertNotIn(str(self.dest),json.dumps(report))

    def test_restart_skips_preexisting_authenticated_days_without_rewrite(self):
        file=self.dest/"existing.twseenc"
        file.write_bytes(b"mocked ciphertext: only mock validates")
        covered=frozenset(m.ALL_2021_DAYS[:9])
        planned,_=m.plan_private_batches(covered,today=self.today)
        touched=[]
        def verified(paths,*,hex_key,start,end):
            self.assertEqual(len(paths),1)
            return {"days":covered,"full_file_integrity_verified":True}
        def preflight(db,*,start,end,today):
            batch=next(b for b in planned if b[0]==start)
            return list(batch),{("twse",str(i)) for i in range(1100,1810)}
        def prepare(db,*,start,end,archive_path,manifest_path,object_key,
                    hex_key,fetcher,today):
            batch=next(b for b in planned if b[0]==start)
            for day in batch:
                fetcher(day)
            return {
                "actual_official_session_dates":[d.isoformat() for d in batch],
                "encrypted_source_rows":700*len(batch),
                "production_postgres_rows_written":0,"line_messages_sent":0}
        report=m.run_local(
            "postgresql://fake",archive_dir=self.dest,hex_key=self.key,
            today=self.today,existing_day_validator=verified,
            preflight_fn=preflight,prepare=prepare,
            fetcher=touched.append,sleeper=lambda _:None)
        self.assertEqual(len(touched),19)
        self.assertTrue(covered.isdisjoint(touched))
        self.assertEqual(report["existing_2021_private_aes_days_authenticated"],9)
        self.assertEqual(report["remaining_unarchived_known_2021_source_days"],0)
        self.assertEqual(file.read_bytes(),b"mocked ciphertext: only mock validates")

    def test_unverified_private_archive_refused_before_database_or_http(self):
        file=self.dest/"unverified.twseenc"
        file.write_bytes(b"untrusted")
        calls=[]
        def bad_evidence(paths,**kw):
            return {"days":frozenset({date(2021,12,1)}),
                    "full_file_integrity_verified":False}
        with self.assertRaisesRegex(ValueError,"Unverified"):
            m.run_local("postgresql://fake",archive_dir=self.dest,
                        hex_key=self.key,today=self.today,
                        existing_day_validator=bad_evidence,
                        preflight_fn=lambda *a,**kw:calls.append("preflight"),
                        fetcher=lambda d:calls.append("GET"))
        self.assertEqual(calls,[])

    def test_calendar_race_is_rejected_before_any_official_request(self):
        calls=[]
        with self.assertRaisesRegex(ValueError,"scope has changed"):
            m.run_local("postgresql://fake",archive_dir=self.dest,
                        hex_key=self.key,today=self.today,
                        preflight_fn=lambda *a,**kw:([],set()),
                        fetcher=lambda d:calls.append(d),
                        prepare=lambda *a,**kw:self.fail("No local archive expected"))
        self.assertEqual(calls,[])

    def test_rolling_window_does_not_rearchive_expired_2021_dates(self):
        future=date(2026,11,24)
        batches,n=m.plan_private_batches(frozenset(),today=future)
        self.assertEqual(n,27)
        self.assertNotIn(date(2021,11,23),[d for b in batches for d in b])

    def test_invalid_existing_coverage_and_public_directory_rejected(self):
        with self.assertRaisesRegex(ValueError,"foreign AES"):
            m.plan_private_batches({date(2022,1,4)},today=self.today)
        with self.assertRaises(ValueError):
            m.run_local("postgresql://fake",archive_dir=self.dest,
                        hex_key="not-a-secret",today=self.today)
        git=self.dest/".git"
        git.mkdir()
        with self.assertRaisesRegex(ValueError,"Git"):
            m.run_local("postgresql://fake",archive_dir=self.dest,
                        hex_key=self.key,today=self.today)
