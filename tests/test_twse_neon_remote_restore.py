"""Fail-closed independent remote disaster recovery without any Neon/LINE writes."""
from datetime import date
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from scripts.twse_local_encrypted_archive import encrypt_rows
from scripts.twse_neon_remote_restore import (
    EXPECTED_HOST, create_backup_manifest, recover_remote_archive,
)
from tests.test_twse_local_encrypted_archive import fake_row

KEY = "market=twse/year=2026/twse-202611.twseenc"
BUCKET = "tw-stock-ai-private-history"
SIGNED = (
    f"https://{EXPECTED_HOST}/{BUCKET}/{KEY}"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=120"
    "&X-Amz-Signature=validsignature"
)


class RemoteResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, chunk_size):
        yield self.payload[:16]
        yield self.payload[16:]


class RemoteTransport:
    def __init__(self, payload):
        self.payload = payload
        self.get_calls = 0

    def get(self, url, *, stream, timeout, allow_redirects):
        assert url == SIGNED
        assert allow_redirects is False
        self.get_calls += 1
        return RemoteResponse(self.payload)


class PrivateEncryptedRestoreTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = Path(self.tmp.name) / "local.twseenc"
        self.key = secrets.token_hex(32)
        self.day = date(2026, 11, 20)
        encrypt_rows([
            fake_row(self.day, "1101"), fake_row(self.day, "2330"),
        ], self.archive, start=self.day, end=self.day, hex_key=self.key)
        self.manifest = create_backup_manifest(
            self.archive, hex_key=self.key, object_key=KEY
        )
        self.remote = RemoteTransport(self.archive.read_bytes())

    def test_recover_without_original_local_file(self):
        self.archive.unlink()
        result = recover_remote_archive(
            self.manifest, hex_key=self.key, url=SIGNED, session=self.remote
        )
        self.assertTrue(result["remote_archive_recovery_verified"])
        self.assertTrue(result["original_local_archive_not_required"])
        self.assertEqual(result["authenticated_rows"], 2)
        self.assertEqual(self.remote.get_calls, 1)
        self.assertEqual(result["neon_rows_written"], 0)
        self.assertFalse(result["five_year_coverage_verified"])

    def test_research_rows_only_after_full_manifest_and_aes_validation(self):
        self.archive.unlink()
        result, rows = recover_remote_archive(
            self.manifest, hex_key=self.key, url=SIGNED,
            session=self.remote, max_rows=2
        )
        self.assertEqual(result["authenticated_rows"], len(rows))
        self.assertEqual([r["stock_id"] for r in rows], ["1101", "2330"])
        self.assertEqual(rows[1]["close"], fake_row(self.day, "2330")["close"])
        self.assertEqual(rows[1]["trade_date"], self.day)

    def test_rejects_mismatch_key_url_manifest_and_oversize(self):
        bad_manifest = dict(self.manifest, encrypted_sha256="0" * 64)
        for manifest, key, url, remote in (
            (bad_manifest, self.key, SIGNED, self.remote),
            (self.manifest, secrets.token_hex(32), SIGNED, self.remote),
            (self.manifest, self.key, SIGNED.replace(EXPECTED_HOST, "example.org"), self.remote),
            (self.manifest, self.key, SIGNED, RemoteTransport(self.remote.payload + b"JUNK")),
        ):
            with self.subTest(case=(manifest, key == self.key, url.split("?")[0])):
                with self.assertRaises((ValueError, RuntimeError)):
                    recover_remote_archive(
                        manifest, hex_key=key, url=url, session=remote
                    )

    def test_wrong_object_not_accepted_before_network(self):
        for k in (
            "market=twse/year=2022/../bad.twseenc",
            "market=tpex/year=2026/twse-202611.twseenc",
            "market=twse/year=2026/unverified.csv",
            "/market=twse/year=2026/twse-202611.twseenc",
        ):
            with self.subTest(k=k), self.assertRaises(ValueError):
                create_backup_manifest(self.archive, hex_key=self.key,
                                       object_key=k)
        changed = dict(self.manifest, object_key="market=twse/year=2023/wrong.twseenc")
        with self.assertRaises(ValueError):
            recover_remote_archive(changed, hex_key=self.key,
                                   url=SIGNED, session=self.remote)
        self.assertEqual(self.remote.get_calls, 0)

    def test_unbounded_research_rejected_before_network(self):
        with self.assertRaises(ValueError):
            recover_remote_archive(self.manifest, hex_key=self.key,
                                   url=SIGNED, session=self.remote,
                                   max_rows=1)
        self.assertEqual(self.remote.get_calls, 0)

    def test_manifest_never_contains_key_or_signed_url(self):
        self.assertNotIn(self.key, str(self.manifest))
        self.assertNotIn(SIGNED, str(self.manifest))
        self.assertEqual(self.manifest["bucket"], BUCKET)
        self.assertTrue(self.manifest["does_not_authorize_source_deletion"])
