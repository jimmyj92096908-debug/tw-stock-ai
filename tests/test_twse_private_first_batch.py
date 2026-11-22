"""First-batch private TWSE archive never writes to Neon or leaks credentials."""
from datetime import date
from pathlib import Path
import json
import secrets
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from cryptography.exceptions import InvalidTag

from scripts.twse_local_encrypted_archive import encrypt_rows
from scripts.twse_private_first_batch import prepare, upload_check
from tests.test_twse_local_encrypted_archive import fake_row
from scripts.twse_neon_remote_restore import EXPECTED_HOST

KEY = "market=twse/year=2026/twse-202611.twseenc"
BASE = ("https://" + EXPECTED_HOST + "/tw-stock-ai-private-history/" + KEY)
PUT = BASE + "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=120&X-Amz-Signature=put"
GET = BASE + "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=120&X-Amz-Signature=get"


class Response:
    def __init__(self, payload=b"", status_code=200):
        self.payload = payload
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        for i in range(0, len(self.payload), chunk_size):
            yield self.payload[i:i+chunk_size]


class Transfer:
    def __init__(self):
        self.payload = None
        self.put_calls = 0
        self.get_calls = 0

    def put(self, url, *, data, headers, timeout, allow_redirects):
        assert url == PUT and not allow_redirects
        self.payload = data.read()
        self.put_calls += 1
        return Response()

    def get(self, url, *, stream, timeout, allow_redirects):
        assert url == GET and stream and not allow_redirects
        self.get_calls += 1
        if self.payload is None:
            return Response(status_code=404)
        return Response(self.payload)


class FirstBatchTests(TestCase):
    def setUp(self):
        self.td = TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.path = Path(self.td.name) / "twse-202611.twseenc"
        self.manifest = Path(self.td.name) / "twse-202611.manifest.json"
        self.key = secrets.token_hex(32)
        self.start = date(2026, 11, 19)
        self.end = date(2026, 11, 20)

    def _fake_export(self, database_url, *, start, end, archive_path, hex_key):
        self.assertEqual(database_url, "postgresql://fake-READ-ONLY")
        self.assertEqual((start, end), (self.start, self.end))
        return encrypt_rows([
            fake_row(self.start, "2330"),
            fake_row(self.end, "2330"),
        ], archive_path, start=start, end=end, hex_key=hex_key)

    def _prepare(self, **kwargs):
        with patch("scripts.twse_private_first_batch.export_neon_readonly",
                   side_effect=self._fake_export) as exported:
            result = prepare(
                database_url="postgresql://fake-READ-ONLY",
                hex_key=self.key,
                start=kwargs.get("start", self.start),
                end=kwargs.get("end", self.end),
                archive_path=self.path,
                manifest_path=self.manifest,
                object_key=kwargs.get("object_key", KEY),
            )
            self.assertEqual(exported.call_count, 1)
        return result

    def test_prepares_verified_private_ciphertext_and_manifest_without_upload(self):
        result = self._prepare()
        self.assertEqual(result["source_rows_exported"], 2)
        self.assertFalse(result["private_object_remote_verified"])
        self.assertEqual(result["production_neon_rows_written_or_deleted"], 0)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["authenticated_rows"], 2)
        self.assertEqual(manifest["object_key"], KEY)
        self.assertNotIn(self.key, str(manifest))
        self.assertNotIn("postgresql://", str(manifest))
        self.assertNotIn(b"11993788.000000", self.path.read_bytes())

    def test_upload_and_independent_remote_recovery_verifies_exact_source(self):
        self._prepare()
        remote = Transfer()
        result = upload_check(
            archive_path=self.path, manifest_path=self.manifest,
            hex_key=self.key, upload_url=PUT, download_url=GET,
            session=remote,
        )
        self.assertTrue(result["remote_recovery_without_local_copy_verified"])
        self.assertEqual(result["source_rows"], 2)
        self.assertEqual(result["production_neon_rows_written_or_deleted"], 0)
        self.assertFalse(result["production_deletion_authorized"])
        self.assertEqual((remote.put_calls, remote.get_calls), (1, 2))

    def test_existing_private_object_is_never_overwritten(self):
        self._prepare()
        remote = Transfer()
        remote.payload = b"original-private-object"
        with self.assertRaisesRegex(RuntimeError, "Cannot prove destination"):
            upload_check(
                archive_path=self.path, manifest_path=self.manifest,
                hex_key=self.key, upload_url=PUT, download_url=GET,
                session=remote,
            )
        self.assertEqual(remote.payload, b"original-private-object")
        self.assertEqual(remote.put_calls, 0)
        self.assertEqual(remote.get_calls, 1)

    def test_wrong_manifest_or_key_fails_before_upload(self):
        self._prepare()
        for mode in ("key", "manifest", "url"):
            remote = Transfer()
            if mode == "manifest":
                doc = json.loads(self.manifest.read_text())
                doc["encrypted_sha256"] = "0" * 64
                self.manifest.write_text(json.dumps(doc))
            with self.subTest(mode=mode), self.assertRaises((ValueError, RuntimeError, InvalidTag)):
                upload_check(
                    archive_path=self.path, manifest_path=self.manifest,
                    hex_key=secrets.token_hex(32) if mode == "key" else self.key,
                    upload_url=PUT.replace("twse-202611", "twse-202610") if mode == "url" else PUT,
                    download_url=GET, session=remote,
                )
            self.assertEqual(remote.put_calls, 0)
            if mode == "manifest":
                # Regenerate the existing manifest without making a new archive.
                from scripts.twse_neon_remote_restore import create_backup_manifest
                self.manifest.write_text(json.dumps(create_backup_manifest(
                    self.path, hex_key=self.key, object_key=KEY
                )))

    def test_duplicate_archive_or_manifest_is_never_overwritten(self):
        self._prepare()
        before = self.manifest.read_bytes()
        with patch("scripts.twse_private_first_batch.export_neon_readonly") as exported:
            with self.assertRaises((ValueError, FileExistsError)):
                prepare(
                    database_url="postgresql://fake-READ-ONLY", hex_key=self.key,
                    start=self.start, end=self.end, archive_path=self.path,
                    manifest_path=self.manifest, object_key=KEY
                )
            exported.assert_not_called()
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_wrong_object_year_and_oversized_range_block_before_query(self):
        with patch("scripts.twse_private_first_batch.export_neon_readonly") as exported:
            with self.assertRaises(ValueError):
                prepare(
                    database_url="postgresql://fake-READ-ONLY", hex_key=self.key,
                    start=self.start, end=self.end, archive_path=self.path,
                    manifest_path=self.manifest,
                    object_key="market=twse/year=2025/bad.twseenc"
                )
            exported.assert_not_called()
