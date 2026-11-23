"""Prospective freeze same-day source SQL and fail-closed no-write regressions.

No production Neon, no SQL query execution, no traffic/compute/paid services.
The separate recorded EXPLAIN plans were read-only estimates, NOT latency.
"""
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scripts import freeze_prospective_research as runner
from src import trained_factor_model as trained
from src.research_forward_freeze import build_frozen_universe
from tests.test_research_forward_freeze import roster, MODEL

ROOT=Path(__file__).resolve().parents[1]
MODEL_PATH=ROOT/"models/tw-factor-ridge-1-research.json"
TODAY=date(2026,11,23)
CAPTURE=datetime(2026,11,23,14,13,tzinfo=ZoneInfo("Asia/Taipei"))


def fake_db(*, price_day=TODAY, score_day=TODAY, rows=None):
    """Mock the exact seven read-only cursor statements inside one snapshot."""
    conn=MagicMock()
    conn.__enter__.return_value=conn
    conn.transaction.return_value.__enter__.return_value=conn
    cur=MagicMock()
    conn.cursor.return_value.__enter__.return_value=cur
    cur.fetchone.side_effect=[
        {"bytes":500_000_000},
        {"latest":price_day},
        {"latest":score_day},
        {"now":CAPTURE},
    ]
    cur.fetchall.return_value=roster(50) if rows is None else rows
    return conn, cur


class SameDayFreezeIndexedTests(unittest.TestCase):
    def test_query_is_date_bound_uses_existing_issuer_allowlist_and_no_global_aggregate(self):
        sql=trained.FROZEN_SAME_DAY_MODEL_SQL
        prior=trained.LATEST_MODEL_SQL
        self.assertIn("official_current_listed",sql)
        self.assertIn("public.daily_composite_scores s",sql)
        self.assertIn("public.daily_prices p",sql)
        self.assertIn("public.stock_master sm",sql)
        self.assertIn("public.model_stock_exclusions",sql)
        self.assertIn("s.as_of_date=%s::date",sql)
        self.assertEqual(sql.count("%s"),1)
        self.assertIn("s.stock_id NOT IN ('1808','1589')",sql)
        self.assertIn("p.trade_date=s.as_of_date",sql)
        self.assertIn("ORDER BY s.market,s.stock_id",sql)
        self.assertNotIn("MAX(as_of_date)",sql)
        self.assertNotIn("latest AS (",sql)
        self.assertNotIn("INSERT INTO",sql)
        self.assertNotIn("UPDATE public.",sql)
        self.assertIn("MAX(as_of_date)",prior)
        self.assertIn("daily_composite_scores",runner.CURRENT_SCORE_SQL)

        for label in ("total_score","technical_score","smc_score",
                      "short_term_score","swing_score","long_term_score",
                      "coverage_weight","signal_close"):
            self.assertIn(label,sql)

    def test_captured_real_snapshot_heads_must_match_then_one_typed_date_parameter(self):
        conn,cur=fake_db()
        with patch.object(runner.psycopg,"connect",return_value=conn):
            report=runner.execute("private-do-not-log",model_path=MODEL_PATH,
                                  apply=False)
        self.assertEqual(report["signal_date"],TODAY.isoformat())
        self.assertEqual(report["universe_count"],50)
        self.assertFalse(report["persisted"])
        self.assertTrue(report["no_database_writes_on_preview"])
        self.assertFalse(report["eligible_for_model_release"])
        self.assertFalse(report["live_trading_approved"])
        statements=cur.execute.call_args_list
        self.assertEqual([x.args[0] for x in statements],[
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
            "SET LOCAL statement_timeout = '30000ms'",
            runner.SIZE_SQL,runner.CURRENT_PRICE_SQL,
            runner.CURRENT_SCORE_SQL,
            trained.FROZEN_SAME_DAY_MODEL_SQL,
            "SELECT clock_timestamp() AS now"
        ])
        self.assertEqual(statements[5].args[1],(TODAY,))
        self.assertEqual(len(statements),7)
        self.assertNotIn(runner.INSERT_SQL,[x.args[0] for x in statements])
        self.assertNotIn("STOCK_FORWARD_RESEARCH_FREEZE_WRITE",
                         repr(conn.call_args_list))
        self.assertEqual(conn.transaction.call_count,1)

    def test_score_day_behind_or_ahead_never_runs_expensive_roster_scan(self):
        for price,score in (
            (TODAY,date(2026,11,20)),
            (date(2026,11,20),TODAY),
            (TODAY,None),
            (None,TODAY),
        ):
            conn,cur=fake_db(price_day=price,score_day=score)
            with self.subTest(price=price,score=score),\
                 patch.object(runner.psycopg,"connect",return_value=conn),\
                 self.assertRaisesRegex(ValueError,"Global latest true market close"):
                runner.execute("private-dsn",model_path=MODEL_PATH,apply=False)
            statements=[x.args[0] for x in cur.execute.call_args_list]
            self.assertEqual(statements[-1],runner.CURRENT_SCORE_SQL)
            self.assertNotIn(trained.FROZEN_SAME_DAY_MODEL_SQL,statements)
            self.assertNotIn(runner.INSERT_SQL,statements)

    def test_owner_excluded_1589_rejected_even_if_mock_bypasses_db_filter(self):
        records=roster(50)
        records[4]["stock_id"]="1589"
        self.assertRaisesRegex(
            ValueError,"Unexpected issuer",
            build_frozen_universe,records,MODEL,model_sha256="a"*64,
            as_of=CAPTURE,latest_market_date=TODAY,
        )
        conn,cur=fake_db(rows=records)
        with patch.object(runner.psycopg,"connect",return_value=conn),\
             self.assertRaisesRegex(ValueError,"Unexpected issuer"):
            runner.execute("private-url",model_path=MODEL_PATH,apply=False)
        self.assertNotIn(runner.INSERT_SQL,
                         [c.args[0] for c in cur.execute.call_args_list])

    def test_free_preflight_and_hard_stop_still_prohibit_new_writes(self):
        root=ROOT
        wf=(root/".github/workflows/composite-after-market-refresh.yml").read_text()
        self.assertIn("steps.prospective_gate.outputs.safe_to_freeze == 'true'",wf)
        self.assertIn("prospective_freeze_preflight_readonly.py",wf)
        self.assertIn("STOCK_FORWARD_RESEARCH_FREEZE_WRITE",wf)
        assert "MAX_DATABASE_BYTES=800_000_000" in (
            root/"scripts/freeze_prospective_research.py").read_text()
        conn,cur=fake_db()
        cur.fetchone.side_effect=[{"bytes":800_000_000}]
        with patch.object(runner.psycopg,"connect",return_value=conn),\
             self.assertRaisesRegex(RuntimeError,"800MB stop"):
            runner.execute("private-url",model_path=MODEL_PATH,apply=False)
        self.assertNotIn(trained.FROZEN_SAME_DAY_MODEL_SQL,
                         [x.args[0] for x in cur.execute.call_args_list])

    def test_snapshot_date_parameter_not_interpolated_from_untrusted_text(self):
        self.assertEqual(trained.FROZEN_SAME_DAY_MODEL_SQL.count("%s::date"),1)
        self.assertNotIn("2026-11-23",trained.FROZEN_SAME_DAY_MODEL_SQL)
        self.assertNotIn("1589",runner.CURRENT_SCORE_SQL)
        # No new SQL executes during mocked tests; original forward-time
        # and no-backfill gates continue to run in build_frozen_universe.
        self.assertFalse(MODEL["production_release_approved"])
        self.assertTrue(MODEL["research_only"])


if __name__=="__main__":
    unittest.main()
