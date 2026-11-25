"""Independent, no-network acceptance of early TWSE historical storage preflight.

A separate literal arithmetic oracle verifies the historical admission
threshold without reusing constants from the implementation under test.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import os
import random
import sys
import unittest
from unittest.mock import patch

from src import twse_dated_history as history


class Cursor:
    def __init__(self, size):
        self.size = size
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if sql.startswith("CREATE") or sql.startswith("INSERT") or sql.startswith("UPDATE"):
            raise AssertionError("Unsafe production write in preflight")

    def fetchone(self):
        return (self.size,)


class Transaction:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Connection:
    def __init__(self, size):
        self.cursor_instance = Cursor(size)
        self.transaction_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def transaction(self):
        self.transaction_count += 1
        return Transaction()

    def cursor(self):
        return self.cursor_instance


class TwseEarlyStorageVerification(unittest.TestCase):
    def test_generated_sizes_match_independent_exact_oracle(self):
        rng = random.Random(20261124)
        samples = [0, 1, 742_799_999, 742_800_000, 749_099_999,
                   749_100_000, 753_147_904, 800_000_000]
        samples.extend(rng.randrange(0, 850_000_001) for _ in range(300))
        for size in samples:
            for days in (1, 2, 4, 8):
                # Reviewer-defined external arithmetic reference, NOT code constants.
                expected = size + 50_000_000 + days * 900_000 < 800_000_000
                with self.subTest(size=size, days=days):
                    self.assertEqual(history.has_source_write_budget(size, days=days),
                                     expected)

    def test_real_preflight_uses_server_enforced_read_only_and_no_http(self):
        fake = Connection(753_147_904)
        with (
            patch.object(history.psycopg, "connect", return_value=fake) as connect,
            patch.object(history, "fetch_official_day",
                         side_effect=AssertionError("source HTTP is forbidden")),
            patch.object(history, "write_missing",
                         side_effect=AssertionError("price writes forbidden")),
        ):
            report = history.read_only_source_preflight("postgresql://dummy")
        self.assertEqual(report["stage"], "ABSTAIN_STORAGE_RESERVE")
        self.assertFalse(report["one_day_capacity_precheck_passed"])
        self.assertFalse(report["production_write_authorized"])
        self.assertFalse(report["actual_neon_plan_quota_verified"])
        self.assertEqual(report["model_release"], "BLOCKED")
        self.assertEqual(report["db_writes"], 0)
        self.assertEqual(report["official_http_calls"], 0)
        self.assertEqual(report["line_messages_sent"], 0)
        self.assertEqual(fake.transaction_count, 1)
        self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])
        sql = fake.cursor_instance.statements
        self.assertEqual(len(sql), 3)
        self.assertIn("REPEATABLE READ, READ ONLY", sql[0])
        self.assertIn("statement_timeout", sql[1])
        self.assertEqual(sql[2], "SELECT pg_database_size(current_database())::bigint")

    def test_blocked_import_cannot_attempt_progress_table_ddl(self):
        fake = Connection(753_147_904)
        allowed = {("twse", str(stock)) for stock in range(1000, 1800)}
        with (
            patch.dict(os.environ, {"STOCK_TWSE_HISTORY_WRITE_ENABLED": "yes"}),
            patch.object(history.psycopg, "connect", return_value=fake),
            patch.object(history, "load_current_twse_allowed", return_value=allowed),
            patch.object(history, "_processed_days", return_value=set()),
            patch.object(history, "fetch_official_day",
                         side_effect=AssertionError("should not fetch")),
            patch.object(history, "write_missing",
                         side_effect=AssertionError("should not write")),
            patch.object(history, "_record_day",
                         side_effect=AssertionError("should not create progress")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Neon Free storage reserve"):
                history.run("postgresql://dummy", apply=True, batch_days=1,
                            lookback_days=7, today=date(2026, 11, 24),
                            pause_seconds=0)
        self.assertEqual(fake.cursor_instance.statements,
                         ["SELECT pg_database_size(current_database())::bigint"])
        self.assertEqual(fake.transaction_count, 0)

    def test_cli_blocked_preflight_is_nonzero_not_a_fake_success(self):
        blocked = {
            "stage": "ABSTAIN_STORAGE_RESERVE",
            "database_bytes": 753_147_904,
            "one_source_day_stress_bytes": 900_000,
            "one_day_capacity_precheck_passed": False,
        }
        buf = StringIO()
        with (
            patch.dict(os.environ, {"DATABASE_URL": "postgresql://dummy"}),
            patch.object(history, "read_only_source_preflight", return_value=blocked),
            patch.object(sys, "argv", ["twse_dated_history.py", "--preflight"]),
            redirect_stdout(buf),
        ):
            with self.assertRaisesRegex(SystemExit, "no official source request"):
                history.main()
        self.assertIn("ABSTAIN_STORAGE_RESERVE", buf.getvalue())
        self.assertNotIn("postgresql://dummy", buf.getvalue())

    def test_manual_dry_run_is_not_blocked_by_preflight_step(self):
        from pathlib import Path
        workflow = Path(".github/workflows/daily-twse-dated-history.yml").read_text(
            encoding="utf-8")
        gate = workflow.index("python src/twse_dated_history.py --preflight")
        preview = workflow.index("python src/twse_dated_history.py --batch-days 1")
        apply = workflow.index("python src/twse_dated_history.py --apply")
        self.assertLess(gate, preview)
        self.assertLess(preview, apply)
        self.assertIn("github.event_name == 'schedule'", workflow)
        self.assertIn("inputs.apply == true", workflow)
        self.assertIn("model_release=BLOCKED",
                      __import__("inspect").getsource(history.main))


if __name__ == "__main__":
    unittest.main()
