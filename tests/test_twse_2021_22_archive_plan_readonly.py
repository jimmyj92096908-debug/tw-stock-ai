"""Offline fail-closed tests: 2021-22 archive planner must NEVER write to Neon."""
import os
from pathlib import Path
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import MagicMock, patch
import unittest

from scripts import twse_2021_22_archive_plan_readonly as audit


class ArchiveBatchPlannerTests(TestCase):
    def setUp(self):
        self.today = date(2026, 11, 23)
        self.meta = {
            "active_twse": 1092,
            "exclusion_1589": 1,
            "database_bytes": 751689728,
            "official_receipt": datetime(2026, 11, 22, tzinfo=timezone.utc),
        }

    def test_module_help_without_pythonpath_is_offline_and_importable(self):
        """Owner PowerShell entrypoint must work without PYTHONPATH=.:src."""
        checkout_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("DATABASE_URL", None)
        result = subprocess.run(
            [sys.executable, "-m", "scripts.twse_2021_22_archive_plan_readonly",
             "--help"],
            cwd=checkout_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--archive-dir", result.stdout)
        self.assertIn("--key-vault", result.stdout)

    def test_realistic_sparse_2021_22_windows_and_frozen_neon_writes(self):
        rows = [
            (date(2021, 11, 23), 20, 0, 0),
            (date(2021, 11, 24), 20, 0, 0),
            (date(2021, 11, 25), 20, 0, 0),
            (date(2022, 1, 4), 20, 0, 0),
            (date(2022, 1, 5), 20, 1, 0),
            (date(2022, 9, 2), 950, 1, 0),
        ]
        result = audit.plan(rows, self.meta, today=self.today)
        self.assertEqual(result["anchored_days_scanned"], 6)
        self.assertEqual(result["sparse_unprocessed_days_to_independently_source_verify"], 4)
        self.assertEqual(result["bounded_private_archive_batch_count"], 2)
        self.assertEqual(result["years"]["2022"]["sparse_with_processed_receipt"], 1)
        self.assertEqual(result["batch_previews"][0]["start"], "2021-11-23")
        self.assertEqual(result["batch_previews"][1]["start"], "2022-01-04")
        self.assertFalse(result["production_source_insert_allowed_by_current_one_day_guard"])
        self.assertTrue(result["owner_exclusion_1589_enforced"])
        self.assertEqual(result["postgres_writes_performed"], 0)
        self.assertEqual(result["private_archive_writes_performed"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["live_model_release"], "BLOCKED")

    def test_month_boundary_and_eight_day_source_batch_limit(self):
        all_days = []
        day = date(2021, 12, 1)
        while len(all_days) < 19:
            if day.weekday() < 5:
                all_days.append(day)
            day += timedelta(days=1)
        result = audit.plan(
            [(d, 20, 0, 0) for d in all_days], self.meta, today=self.today
        )
        self.assertEqual([x["known_sparse_anchor_days"] for x in result["batch_previews"]],
                         [8, 8, 3])
        self.assertEqual(sum(x["known_sparse_anchor_days"]
                             for x in result["batch_previews"]), 19)
        for batch in result["batch_previews"]:
            self.assertTrue(batch["start"].startswith("2021-12"))
            self.assertTrue(batch["end"].startswith("2021-12"))
            self.assertLessEqual(batch["known_sparse_anchor_days"], 8)
            self.assertFalse(batch["official_source_downloaded_here"])
            self.assertFalse(batch["encrypted_owner_archive_verified_here"])
            self.assertIn(" preview ", batch["preview_command"])

    def test_stale_or_missing_current_official_listing_is_blocked(self):
        invalid = [
            {"active_twse": 0},
            {"exclusion_1589": 0},
            {"official_receipt": datetime(2026, 11, 1, tzinfo=timezone.utc)},
            {"database_bytes": -1},
        ]
        for part in invalid:
            with self.subTest(part=part), self.assertRaises(ValueError):
                audit.plan([(date(2022, 1, 4), 20, 0, 0)],
                           {**self.meta, **part}, today=self.today)

    def test_bad_dates_duplicates_and_impossible_receipts_fail_closed(self):
        valid = (date(2022, 1, 4), 20, 0, 0)
        bad_cases = [
            [valid, valid],
            [(date(2021, 11, 22), 20, 0, 0)],
            [(date(2022, 1, 8), 20, 0, 0)],
            [(date(2022, 1, 4), 0, 0, 0)],
            [(date(2022, 1, 4), 20, 1, 1)],
            [(date(2022, 1, 4), 20, 0, 2)],
            [(date(2023, 1, 2), 20, 0, 0)],
            [(date(2022, 1, 5), 20, 0, 0), valid],
        ]
        for rows in bad_cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                audit.plan(rows, self.meta, today=self.today)

    def test_five_year_cutoff_and_previous_year_boundary(self):
        self.assertEqual(audit.rolling_start(date(2026, 11, 23)),
                         date(2021, 11, 23))
        self.assertEqual(audit.rolling_start(date(2024, 2, 29)),
                         date(2019, 2, 28))
        with self.assertRaises(ValueError):
            audit.plan([(date(2022, 1, 4), 20, 0, 0)], self.meta,
                       today=date(2028, 1, 1))

    def test_neon_connection_explicit_read_only_without_pooler_startup_gucs(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchone.return_value = self.meta
        cursor = MagicMock()
        cursor.fetchall.return_value = [(date(2022, 1, 4), 20, 0, 0)]
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch("psycopg.connect", return_value=conn) as connect:
            out = audit.read_only_plan("postgresql://fake", today=self.today)
        self.assertEqual(out["sparse_unprocessed_days_to_independently_source_verify"], 1)
        self.assertNotIn("options", connect.call_args.kwargs)
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertEqual(statements[0],
                         "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        self.assertIn("SET LOCAL statement_timeout", statements[1])
        self.assertIn("official_current_listed", statements[2])
        self.assertIn("stock_id='1589'", statements[2])
        self.assertIn("p.stock_id = '2330'", audit.CALENDAR_SQL)
        for query in (audit.METADATA_SQL, audit.CALENDAR_SQL):
            self.assertNotIn("INSERT INTO", query.upper())
            self.assertNotIn("DELETE FROM", query.upper())
            self.assertNotIn("UPDATE PUBLIC", query.upper())
        conn.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
