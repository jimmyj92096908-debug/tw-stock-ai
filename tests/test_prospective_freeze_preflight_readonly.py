"""Synthetic zero-write future-freeze preflight, no live Neon or paid API."""
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch
import json
from zoneinfo import ZoneInfo

from scripts import prospective_freeze_preflight_readonly as p
from scripts import neon_free_meter_guard as meter

NOW = datetime(2026, 11, 23, 14, 9, tzinfo=ZoneInfo("Asia/Taipei"))
SCORE_DATE = date(2026, 11, 23)


def valid_usage():
    return {
        "id":meter.PROJECT_ID,
        "data_transfer_bytes":320_000_000,
        "compute_time_seconds":3010,
        "consumption_period_end":"2026-12-01T00:00:00Z",
    }


def sample(**kwargs):
    original=dict(
        db_bytes=510_000_000,
        market_day=SCORE_DATE, score_day=SCORE_DATE,
        captured_at=NOW, transfer_usage=valid_usage())
    original.update(kwargs)
    return p.verdict(**original)


class ResearchFreezePreflightTests(TestCase):
    def test_same_day_and_authenticated_meter_can_try_prior_freeze_only(self):
        ready=sample()
        self.assertEqual(ready["status"],"READY_FOR_EXISTING_AUTHORIZED_FREEZE")
        self.assertTrue(ready["safe_to_attempt_existing_authorized_freeze"])
        self.assertTrue(ready["project_network_transfer_verified"])
        self.assertFalse(ready["live_trading_approved"])
        self.assertFalse(ready["holdout_alpha_proven"])
        self.assertFalse(ready["paid_services_authorized"])
        self.assertEqual(ready["model_release"],"BLOCKED")
        self.assertEqual(ready["neon_database_writes"],0)

    def test_actual_753mb_like_size_blocks_even_with_matched_dates(self):
        x=sample(db_bytes=753_147_904)
        self.assertEqual(x["status"],"ABSTAIN_STORAGE_WARN")
        self.assertFalse(x["safe_to_attempt_existing_authorized_freeze"])
        self.assertFalse(x["project_network_transfer_verified"])
        self.assertEqual(x["conservative_storage_warning_bytes"],650_000_000)
        for n in (650_000_000,800_000_000):
            self.assertFalse(sample(db_bytes=n)[
                "safe_to_attempt_existing_authorized_freeze"])

    def test_latest_score_date_mismatch_rejected_not_use_stale_score(self):
        stale=sample(score_day=date(2026,11,20))
        self.assertEqual(stale["status"],"ABSTAIN_MARKET_SCORE_DAY_MISMATCH")
        self.assertFalse(stale["safe_to_attempt_existing_authorized_freeze"])
        ahead=sample(market_day=date(2026,11,20))
        self.assertEqual(ahead["status"],"ABSTAIN_MARKET_SCORE_DAY_MISMATCH")
        for dates in ((None,SCORE_DATE),(SCORE_DATE,None)):
            s=sample(market_day=dates[0],score_day=dates[1])
            self.assertEqual(s["status"],"ABSTAIN_MISSING_REAL_MARKET_OR_SCORE_DAY")

    def test_historical_time_and_missing_network_meter_both_block(self):
        self.assertEqual(sample(
            captured_at=datetime(2026,11,23,13,29,
                                 tzinfo=ZoneInfo("Asia/Taipei")))["status"],
            "ABSTAIN_OUTSIDE_PROSPECTIVE_TIME")
        self.assertEqual(sample(
            captured_at=datetime(2026,11,25,10,10,
                                 tzinfo=ZoneInfo("Asia/Taipei")))["status"],
            "ABSTAIN_OUTSIDE_PROSPECTIVE_TIME")
        self.assertEqual(sample(transfer_usage=None)["status"],
                         "ABSTAIN_NO_VERIFIED_NEON_TRANSFER")
        self.assertEqual(sample(transfer_usage={
            **valid_usage(),"data_transfer_bytes":4_500_000_000,
        })["status"],"ABSTAIN_NEON_TRANSFER_PAUSED")
        with self.assertRaises(ValueError):
            sample(transfer_usage={**valid_usage(),"id":"wrong-Neon-project"})
        with self.assertRaises(ValueError):
            sample(db_bytes=True)

    def test_readonly_database_uses_small_queries_and_never_fetches_roster(self):
        fake=MagicMock()
        fake.__enter__.return_value=fake
        fake.transaction.return_value.__enter__.return_value=fake
        fake.cursor.return_value.__enter__.return_value=fake
        cursor=fake.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect=[
            {"bytes":510_000_000},
            {"market_day":SCORE_DATE,"score_day":SCORE_DATE,
             "captured_at":NOW},
        ]
        with patch.object(p.psycopg,"connect",return_value=fake) as conn,\
             patch.object(p,"fetch_meter",return_value=valid_usage()) as network:
            with TemporaryDirectory() as d:
                report=Path(d)/"gate.json"
                gh=Path(d)/"output"
                actual=p.run(database_url="private-not-shared",
                             neon_api_key="token-not-shared",
                             report_path=report,github_output_path=gh)
                self.assertTrue(actual["safe_to_attempt_existing_authorized_freeze"])
                self.assertIn("safe_to_freeze=true",gh.read_text())
                self.assertEqual(json.loads(report.read_text())["model_release"],
                                 "BLOCKED")
        network.assert_called_once_with("token-not-shared")
        self.assertEqual(conn.call_args.kwargs["options"],
                         "-c default_transaction_read_only=on")
        sql=[x.args[0] for x in fake.execute.call_args_list]
        self.assertEqual(sql,[]) # all through cursor
        cursor=fake.cursor.return_value.__enter__.return_value
        queries=[x.args[0] for x in cursor.execute.call_args_list]
        self.assertIn("READ ONLY",queries[0])
        self.assertIn("statement_timeout",queries[1])
        self.assertEqual(queries[2],p.SIZE_SQL)
        self.assertEqual(queries[3],p.HEAD_SQL)
        self.assertEqual(len(queries),4)
        self.assertNotIn("daily_adjusted_prices"," ".join(queries))
        self.assertNotIn("INSERT INTO"," ".join(queries))

    def test_warning_memory_cannot_trigger_head_query_or_remote_meter(self):
        fake=MagicMock()
        fake.__enter__.return_value=fake
        fake.cursor.return_value.__enter__.return_value=fake
        cursor=fake.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value={"bytes":753_147_904}
        with patch.object(p.psycopg,"connect",return_value=fake),\
             patch.object(p,"fetch_meter") as remote:
            result=p.run(database_url="private",
                         neon_api_key="even-if-present")
        self.assertEqual(result["status"],"ABSTAIN_STORAGE_WARN")
        remote.assert_not_called()
        cursor=fake.cursor.return_value.__enter__.return_value
        statements=[x.args[0] for x in cursor.execute.call_args_list]
        self.assertNotIn(p.HEAD_SQL,statements)
        self.assertEqual(statements[-1],p.SIZE_SQL)

    def test_missing_credential_or_db_error_abstains_redacted(self):
        secret="postgres://secret-user:secret-pass@hidden"
        with TemporaryDirectory() as folder:
            out=Path(folder)/"result.json"
            actual=p.run(database_url="",report_path=out)
            self.assertEqual(actual["status"],"ABSTAIN_READONLY_PREFLIGHT_UNAVAILABLE")
            with patch.object(p.psycopg,"connect",
                              side_effect=RuntimeError(secret)):
                actual=p.run(database_url=secret,report_path=out)
                self.assertEqual(actual["status"],
                                 "ABSTAIN_READONLY_PREFLIGHT_UNAVAILABLE")
            self.assertNotIn("secret-pass",out.read_text())
        self.assertFalse(actual["safe_to_attempt_existing_authorized_freeze"])

    def test_old_score_and_current_workflow_gate_must_not_weaken(self):
        root=Path(__file__).resolve().parents[1]
        old=(root/"src/research_forward_freeze.py").read_text(encoding="utf-8")
        self.assertIn("Global latest true market close and score day differ",old)
        self.assertIn("Cannot backdate or freeze an old signal date",old)
        self.assertIn("Post-close frozen snapshot too late",old)
        for path in (
            ".github/workflows/composite-after-market-refresh.yml",
            ".github/workflows/prospective-free-safe-daily.yml",
        ):
            wf=(root/path).read_text(encoding="utf-8")
            self.assertIn("prospective_freeze_preflight_readonly.py",wf)
            self.assertIn("safe_to_freeze == 'true'",wf)
            self.assertIn("prospective-freeze-preflight",wf)
        for prefix in ("LINE_CHANNEL_ACCESS_TOKEN",
                       "STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED"):
            self.assertNotIn(prefix,
                (root/".github/workflows/prospective-free-safe-daily.yml").read_text())
