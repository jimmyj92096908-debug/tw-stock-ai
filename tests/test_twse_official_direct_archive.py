"""Official TWSE source-to-AES path keeps Neon READ ONLY at capacity."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import secrets
import subprocess
import sys
from unittest import TestCase
from unittest.mock import MagicMock, patch
from decimal import Decimal

from scripts import twse_official_direct_archive as direct
from scripts.twse_local_encrypted_archive import verify_archive
from scripts.twse_neon_remote_restore import _validate_manifest
from tests.test_twse_stateless_2022_source_probe import rows

START = date(2022, 1, 1)
END = date(2022, 1, 31)
DAYS = (date(2022, 1, 4), date(2022, 1, 5))
KEY = "market=twse/year=2022/twse-early-202201.twseenc"
FAKE_URL = "postgresql://private-fake"


def fake_connection():
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = MagicMock()
    cur.fetchall.return_value = [(DAYS[0], 20), (DAYS[1], 40)]
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


class DirectOfficialEncryptedArchiveTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "twse-early-202201.twseenc"
        self.manifest = Path(self.temp.name) / "twse-early-202201.manifest.json"
        self.key = secrets.token_hex(32)
        self.allowed = {("twse", row["stock_id"]) for row in rows(DAYS[0])}
        self.assertGreaterEqual(len(self.allowed), 700)

    def _mock_preflight(self, conn, *, receipt=None):
        return (
            patch("psycopg.connect", return_value=conn),
            patch.object(direct, "load_current_twse_allowed",
                         return_value=self.allowed),
            patch.object(direct, "_processed_days",
                         return_value=receipt if receipt is not None else set()),
        )

    def test_only_sparse_unprocessed_existing_2330_dates_are_selected(self):
        self.assertEqual(
            direct.choose_sparse_sessions(
                [(DAYS[0], 20), (DAYS[1], 40)],
                start=START, end=END, processed={DAYS[0]},
                today=date(2026, 11, 22)
            ),
            [DAYS[1]]
        )
        self.assertIn("stock_id='2330'", direct.GAP_SQL)
        self.assertIn("twse_history_day_progress", direct.GAP_SQL)
        self.assertIn("p.status IN ('imported','closed')", direct.GAP_SQL)
        for forbidden in ("INSERT INTO", "DELETE FROM", "UPDATE public.", "DROP TABLE"):
            self.assertNotIn(forbidden, direct.GAP_SQL.upper())
        with self.assertRaises(ValueError):
            direct.choose_sparse_sessions(
                [(DAYS[1], 40), (DAYS[0], 20)],
                start=START, end=END, processed=set(),
                today=date(2026, 11, 22)
            )
        with self.assertRaises(ValueError):
            direct.choose_sparse_sessions(
                [(DAYS[0], 700)], start=START, end=END,
                processed=set(), today=date(2026, 11, 22)
            )
        with self.assertRaises(ValueError):
            direct.choose_sparse_sessions(
                [(DAYS[0], 20)], start=START, end=END,
                processed={DAYS[0]}, today=date(2026, 11, 22)
            )

    def test_sql_receipt_and_roster_are_explicitly_read_only(self):
        conn = fake_connection()
        a, b, c = self._mock_preflight(conn)
        with a as connected, b, c:
            days, allowed = direct.preflight(
                FAKE_URL, start=START, end=END,
                today=date(2026, 11, 22)
            )
        self.assertEqual(days, list(DAYS))
        self.assertEqual(len(allowed), len(self.allowed))
        self.assertIn("default_transaction_read_only=on",
                      connected.call_args.kwargs["options"])
        self.assertEqual(
            conn.execute.call_args_list[0].args[0],
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        query = conn.cursor.return_value.__enter__.return_value.execute.call_args
        self.assertEqual(query.args[1], (START, END))
        self.assertIn("LIMIT 8", query.args[0])

    def test_official_two_dates_to_private_aes_with_decimal_roundtrip(self):
        calls = []
        def source(day):
            calls.append(day)
            feed = rows(day)
            # Simulate an excluded issuer and a code not in current issuer list.
            feed += [
                {**feed[0], "stock_id":"1589"},
                {**feed[0], "stock_id":"9999"},
            ]
            return feed
        with patch.object(direct,"preflight",
                          return_value=(list(DAYS), self.allowed)):
            result = direct.prepare_official_archive(
                FAKE_URL, start=START, end=END,
                archive_path=self.archive, manifest_path=self.manifest,
                object_key=KEY, hex_key=self.key,
                fetcher=source, today=date(2026, 11, 22)
            )
        self.assertEqual(calls, list(DAYS))
        self.assertEqual(result["encrypted_source_rows"], 1440)
        self.assertEqual(result["production_postgres_rows_written"], 0)
        self.assertEqual(result["production_postgres_rows_deleted"], 0)
        self.assertFalse(result["remote_private_archive_verified"])
        self.assertFalse(result["historical_five_year_completeness_verified"])
        source_proof = verify_archive(self.archive, hex_key=self.key)
        self.assertEqual(source_proof["sample_rows"], 1440)
        manifest = _validate_manifest(json.loads(self.manifest.read_text()))
        self.assertEqual(manifest["authenticated_rows"], 1440)
        self.assertEqual(manifest["object_key"], KEY)
        self.assertNotIn("1589", self.archive.read_bytes().decode("latin1").split("C", 1)[0])
        self.assertNotIn("9999", str(manifest))
        self.assertNotIn(self.key, self.manifest.read_text())
        restored = []
        verify_archive(self.archive, hex_key=self.key, on_verified_row=restored.append)
        self.assertEqual(restored[0]["close"], Decimal("100.2500"))
        self.assertEqual(restored[0]["trade_date"], DAYS[0])
        self.assertTrue(restored[0]["retrieved_at"].tzinfo is not None)
        self.assertTrue(all(row["stock_id"] not in ("1589","9999")
                            for row in restored))

    def test_bad_second_day_source_refuses_partial_archive(self):
        def source(day):
            return rows(day) if day == DAYS[0] else rows(day, number=200)
        with patch.object(direct,"preflight",
                          return_value=(list(DAYS), self.allowed)):
            with self.assertRaises(ValueError):
                direct.prepare_official_archive(
                    FAKE_URL, start=START, end=END,
                    archive_path=self.archive, manifest_path=self.manifest,
                    object_key=KEY, hex_key=self.key,
                    fetcher=source, today=date(2026, 11, 22)
                )
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.manifest.exists())

    def test_bad_key_path_or_year_blocks_before_any_source(self):
        with patch.object(direct, "preflight") as sql:
            for value in ("not-a-key", "", "ab" * 31):
                with self.subTest(key_len=len(value)), self.assertRaises(ValueError):
                    direct.prepare_official_archive(
                        FAKE_URL, start=START, end=END,
                        archive_path=self.archive, manifest_path=self.manifest,
                        object_key=KEY, hex_key=value,
                        today=date(2026, 11, 22)
                    )
            with self.assertRaises(ValueError):
                direct.prepare_official_archive(
                    FAKE_URL, start=START, end=END,
                    archive_path=self.archive, manifest_path=self.manifest,
                    object_key="market=twse/year=2023/wrong.twseenc",
                    hex_key=self.key, today=date(2026, 11, 22)
                )
            sql.assert_not_called()

    def test_rolling_five_year_and_35_day_limit(self):
        direct.validate_bounds(START, END, today=date(2026, 11, 22))
        for start,end in (
            (date(2021, 11, 21), date(2021, 11, 22)),
            (date(2022, 1, 1), date(2022, 3, 1)),
            (date(2026, 11, 22), date(2026, 11, 22)),
            (date(2022, 12, 30), date(2023, 1, 3)),
        ):
            with self.subTest(start=start,end=end), self.assertRaises(ValueError):
                direct.validate_bounds(start,end,today=date(2026, 11, 22))

    def test_source_duplicate_or_bad_market_date_fails_closed(self):
        for way in ("duplicate", "date", "source"):
            fake = rows(DAYS[0])
            if way == "duplicate":
                fake.append(fake[0].copy())
            elif way == "date":
                fake[0]["trade_date"] = DAYS[1]
            else:
                fake[0]["source"] = "UNVERIFIED"
            # A full batch must fail, not silently skip a malformed eligible bar.
            with self.subTest(way=way):
                with self.assertRaises(ValueError):
                    list(direct._canonical_source_rows(
                        lambda _:fake, [DAYS[0]], self.allowed
                    ))

    def test_no_remote_upload_or_line_in_direct_source_module(self):
        self.assertNotIn("requests.put", direct.prepare_official_archive.__code__.co_names)
        self.assertEqual(direct.MAX_REQUESTED_SESSIONS, 8)
        self.assertEqual(direct.MAX_CALENDAR_SPAN_DAYS, 35)


class OwnerLocalCliImportTests(TestCase):
    def test_owner_local_cli_import_without_pythonpath(self):
        """Windows PowerShell owner path must work without CI-only PYTHONPATH=.:src."""
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        # `--help` imports the real package graph without connecting to Neon,
        # requesting official source data, or writing encrypted artifacts.
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.twse_official_direct_archive", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            env=env, capture_output=True, text=True, timeout=25,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("preview", completed.stdout)
        self.assertIn("archive", completed.stdout)
