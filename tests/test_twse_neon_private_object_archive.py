"""Offline tests for private Neon AES archive transport; no actual network."""
from datetime import date
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from scripts.twse_neon_private_object_archive import (
    approved_signed_url, upload_encrypted_archive, verify_remote_copy,
    load_verified_research_slice,
)
from scripts.twse_local_encrypted_archive import encrypt_rows
from tests.test_twse_local_encrypted_archive import fake_row

HOST = "br-purple-smoke-a1t9dmzz.storage.c-1.ap-southeast-1.aws.neon.tech"
KEY_PATH = "tw-stock-ai-private-history/market=twse/year=2026/sample.twseenc"
SIG = "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=120&X-Amz-Signature=abcdef"
URL = f"https://{HOST}/{KEY_PATH}?{SIG}"


class GoodResponse:
    status_code = 200

    def __init__(self, payload=b""):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.payload), chunk_size):
            yield self.payload[offset:offset+chunk_size]


class OfflineTransport:
    def __init__(self):
        self.payload = None
        self.uploaded = 0
        self.downloaded = 0

    def put(self, url, *, data, headers, timeout, allow_redirects):
        assert url == URL
        assert headers == {"Content-Type": "application/octet-stream"}
        assert allow_redirects is False
        self.payload = data.read()
        self.uploaded += 1
        return GoodResponse()

    def get(self, url, *, stream, timeout, allow_redirects):
        assert url == URL
        assert stream is True
        assert allow_redirects is False
        self.downloaded += 1
        return GoodResponse(self.payload)


class NeonPrivateArchiveSafetyTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "verified.twseenc"
        self.key = secrets.token_hex(32)
        first = date(2026, 11, 19)
        last = date(2026, 11, 20)
        rows = [fake_row(first, "2330"), fake_row(last, "1101")]
        encrypt_rows(rows, self.archive, start=first, end=last, hex_key=self.key)

    def test_only_shortlived_neon_private_signed_tls_urls(self):
        self.assertEqual(
            approved_signed_url(URL),
            (HOST, f"/{KEY_PATH}"),
        )
        for url in (
            URL.replace("https://", "http://"),
            URL.replace(HOST, "example.com"),
            URL.replace("tw-stock-ai-private-history", "public"),
            URL.replace("sample.twseenc", "sample.csv"),
            URL.replace("X-Amz-Signature", "Not-Signed"),
            URL.replace("120&", "7200&"),
            URL.replace(HOST, "br-bad.storage.c-1.ap-southeast-1.aws.neon.tech.evil.org"),
            URL.replace("https://", "https://attacker:pwd@"),
        ):
            with self.subTest(url=url.split("?")[0]), self.assertRaises(ValueError):
                approved_signed_url(url)

    def test_aes_verified_upload_then_independent_remote_download(self):
        remote = OfflineTransport()
        upload = upload_encrypted_archive(
            self.archive, hex_key=self.key, url=URL, session=remote,
        )
        self.assertTrue(upload["encrypted_archive_uploaded"])
        self.assertEqual(upload["authenticated_source_rows"], 2)
        self.assertFalse(upload["remote_download_and_integrity_verified"])
        proof = verify_remote_copy(
            self.archive, hex_key=self.key, url=URL, session=remote,
        )
        self.assertEqual(remote.uploaded, 1)
        self.assertEqual(remote.downloaded, 1)
        self.assertEqual(proof["authenticated_restored_rows"], 2)
        self.assertTrue(proof["remote_download_and_integrity_verified"])
        self.assertTrue(proof["exact_decimal_and_source_vintage_verified"])
        self.assertFalse(proof["five_year_coverage_verified"])
        self.assertEqual(proof["neon_price_rows_deleted"], 0)

    def test_corrupt_remote_archive_refuses_integrity_proof(self):
        remote = OfflineTransport()
        upload_encrypted_archive(
            self.archive, hex_key=self.key, url=URL, session=remote
        )
        # Fixed replacement can accidentally equal the randomized AES tag byte.
        # XOR one bit to guarantee actual corruption on every execution.
        original = remote.payload
        remote.payload = original[:-1] + bytes([original[-1] ^ 1])
        self.assertNotEqual(remote.payload, original)
        self.assertEqual(len(remote.payload), len(original))
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            verify_remote_copy(self.archive, hex_key=self.key,
                               url=URL, session=remote)

    def test_invalid_key_fails_before_any_remote_request(self):
        remote = OfflineTransport()
        with self.assertRaises(Exception):
            upload_encrypted_archive(
                self.archive, hex_key=secrets.token_hex(32),
                url=URL, session=remote,
            )
        self.assertEqual(remote.uploaded, 0)
        self.assertEqual(remote.downloaded, 0)

    def test_research_loader_releases_only_fully_verified_rows(self):
        rows = load_verified_research_slice(
            self.archive, hex_key=self.key, max_rows=2
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["stock_id"], "2330")
        self.assertEqual(rows[0]["close"], fake_row(date(2026, 11, 19), "2330")["close"])
        self.assertEqual(rows[0]["trade_date"], date(2026, 11, 19))
        with self.assertRaises(ValueError):
            load_verified_research_slice(
                self.archive, hex_key=self.key, max_rows=1
            )
        altered = self.archive.read_bytes()[:-7]
        self.archive.write_bytes(altered)
        with self.assertRaises(Exception):
            load_verified_research_slice(
                self.archive, hex_key=self.key, max_rows=2
            )

    def test_remote_redirect_is_never_followed(self):
        class RedirectTransport(OfflineTransport):
            def put(self, *args, **kwargs):
                assert kwargs["allow_redirects"] is False
                return Mock(status_code=307)
        remote = RedirectTransport()
        with self.assertRaisesRegex(RuntimeError, "upload failed"):
            upload_encrypted_archive(self.archive,hex_key=self.key,
                                     url=URL,session=remote)

    def test_url_host_excludes_line_or_arbitrary_cloud_destination(self):
        self.assertNotIn("line.me", HOST)
        self.assertNotIn("github.com", HOST)
        with self.assertRaises(ValueError):
            approved_signed_url("https://raw.githubusercontent.com/" +
                                KEY_PATH + "?" + SIG)
