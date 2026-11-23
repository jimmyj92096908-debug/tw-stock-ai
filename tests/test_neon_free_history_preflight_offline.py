"""Pure offline regression gates for zero-cost 2021 backfill feasibility."""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.neon_free_history_preflight_offline import evaluate, STOP_BYTES, RESERVE_BYTES

ROOT = Path(__file__).resolve().parents[1]


def owner_union():
    return {
        "scope": "OWNER_2021_TWSE_AES_NEON_CURRENT_LISTED_28DAY_STOCK_DATE_UNION_READONLY",
        "prior_2021_aes_source_stock_date_pairs": 26120,
        "prior_2021_neon_source_stock_date_pairs": 552,
        "aes_neon_overlapping_source_stock_date_pairs": 552,
        "aes_exclusive_source_stock_date_pairs": 25568,
        "neon_exclusive_source_stock_date_pairs": 0,
        "actual_deduplicated_aes_neon_stock_date_pairs": 26120,
        "current_stocks_with_no_source_day_in_2021": 153,
        "authenticated_owner_2021_source_dates": 28,
        "model_release": "BLOCKED",
        "production_neon_writes": 0,
        "line_messages_sent": 0,
    }


def owner_listing():
    return {
        "scope": "OWNER_2021_TWSE_153_ZERO_SOURCE_CURRENT_OFFICIAL_LISTING_DATE_TRIAGE",
        "no_2021_aes_or_neon_source_issuer_count": 153,
        "prior_revalidated_2021_aes_neon_deduplicated_stock_date_pairs": 26120,
        "zero_source_2021_prioritize_manual_historical_listing_research": 0,
        "model_release": "BLOCKED",
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "current_listing_year_and_period_bucket_counts": {
            "current_listing_on_or_before_first_2021_source_day": 0,
            "current_listing_between_first_and_last_2021_source_days": 0,
            "current_listing_after_last_2021_source_day_in_2021": 0,
            "current_listing_in_2022": 24,
            "current_listing_in_2023": 27,
            "current_listing_in_2024": 37,
            "current_listing_in_2025": 35,
            "current_listing_in_2026": 30,
            "current_listing_date_missing_or_invalid": 0,
        },
    }


def snapshot():
    return {
        "pg_database_bytes": 751689728,
        "neon_branch_logical_bytes": 775184384,
        "neon_branch_limit_bytes": 1073741824,
        "daily_prices_relation_bytes": 505905152,
        "daily_prices_rows": 2012173,
    }


class NeonFreeHistoryPreflightTests(unittest.TestCase):
    def test_live_observed_numbers_prove_stop_but_not_import(self):
        r = evaluate(snapshot(), owner_union(), owner_listing())
        self.assertEqual(r["existing_guard_headroom_before_any_growth_bytes"], -1689728)
        self.assertTrue(r["existing_guard_blocks_even_zero_estimated_growth"])
        self.assertEqual(r["2021_aes_exclusive_source_stockdate_keys_not_in_neon_receipt"], 25568)
        self.assertEqual(r["authenticated_2021_union_source_stockdate_keys"], 26120)
        self.assertEqual(r["remaining_logical_branch_bytes_before_limit"], 298557440)
        self.assertGreater(r["indicative_2021_candidate_rewrite_allowance_bytes_not_a_quota_guarantee"], 0)
        self.assertFalse(r["safe_to_run_production_backfill"])
        self.assertEqual(r["neon_writes"], 0)
        self.assertEqual(r["line_messages_sent"], 0)
        self.assertEqual(r["model_release"], "BLOCKED")

    def test_headroom_does_not_authorize_writes(self):
        s = snapshot()
        s["pg_database_bytes"] = 650_000_000
        r = evaluate(s, owner_union(), owner_listing())
        self.assertFalse(r["existing_guard_blocks_even_zero_estimated_growth"])
        self.assertFalse(r["safe_to_run_production_backfill"])
        self.assertTrue(r["requires_independent_restore_test_and_fresh_capacity_check"])

    def test_tampered_receipts_and_snapshot_fail_closed(self):
        for key, value in (("aes_neon_overlapping_source_stock_date_pairs", 551),
                           ("aes_exclusive_source_stock_date_pairs", 25569),
                           ("model_release", "APPROVED")):
            u = owner_union()
            u[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evaluate(snapshot(), u, owner_listing())
        for key, value in (("current_listing_in_2022", 23),
                           ("current_listing_on_or_before_first_2021_source_day", 1)):
            l = owner_listing()
            l["current_listing_year_and_period_bucket_counts"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evaluate(snapshot(), owner_union(), l)
        for key, value in (("neon_branch_logical_bytes", 2_000_000_000),
                           ("pg_database_bytes", -5),
                           ("daily_prices_rows", 0),
                           ("daily_prices_relation_bytes", True)):
            s = snapshot()
            s[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evaluate(s, owner_union(), owner_listing())

    def test_existing_guard_thresholds_match_scheduled_guard(self):
        source = ROOT / "scripts" / "indicator_capacity_guard.py"
        if not source.is_file():
            self.skipTest("Full repository guard is not present in isolated fixture")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        values = {
            t.id: v.value
            for n in tree.body
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name)
            if isinstance(v := n.value, ast.Constant)
        }
        self.assertEqual(values["STOP_BYTES"], STOP_BYTES)
        self.assertEqual(values["RESERVE_BYTES"], RESERVE_BYTES)

    def test_cli_no_overwrite_and_no_secret_output(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            a = base / "union.json"
            b = base / "listing.json"
            c = base / "capacity.json"
            out = base / "report.json"
            for p, obj in ((a, owner_union()), (b, owner_listing()), (c, snapshot())):
                p.write_text(json.dumps(obj), encoding="utf-8")
            cmd = [
                sys.executable, "-m", "scripts.neon_free_history_preflight_offline",
                "--capacity-snapshot", str(c), "--owner-2021-union", str(a),
                "--owner-153-listing", str(b), "--out", str(out),
            ]
            good = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertTrue(out.exists())
            console = json.loads(good.stdout)
            self.assertEqual(console["status"], "NEON_FREE_2021_HISTORY_ADMISSION_EVIDENCE_PASS")
            before = out.read_bytes()
            denied = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(out.read_bytes(), before)
            self.assertNotIn("DATABASE_URL", denied.stderr)


if __name__ == "__main__":
    unittest.main()
