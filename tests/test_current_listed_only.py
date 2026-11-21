"""Owner rule: exclude all stocks absent current official TWSE TPEx list."""
from datetime import datetime,timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE
from src.factor_model import LATEST_RANKING_SQL
from src.factor_model_v2 import ADJUSTED_EVALUATION_SQL
from src.trained_factor_model import LATEST_MODEL_SQL,TRAINING_SQL
from src import send_line_report
from scripts import current_listed_only_audit as m

ROOT=Path(__file__).resolve().parents[1]

def totals():
    return {
        "last_current_official_observed_at":datetime(2026,11,21,15,44,tzinfo=timezone.utc),
        "official_current_listing_count":1990,
        "current_master_count":1991,
        "matched_current_exchange_issuers":1990,
        "master_only_excluded":1,
        "official_missing_from_current_master":0,
    }

class CurrentOnlyStockModelTests(TestCase):
    def test_official_list_snapshot_not_stale_stock_master_is_authority(self):
        self.assertIn("public.official_issuer_weekly_snapshots",CURRENT_OFFICIAL_LISTED_CTE)
        self.assertIn("public.official_issuer_snapshot_corrections",CURRENT_OFFICIAL_LISTED_CTE)
        self.assertIn("INTERVAL '14 days'",CURRENT_OFFICIAL_LISTED_CTE)
        self.assertIn("ORDER BY observed_at DESC",CURRENT_OFFICIAL_LISTED_CTE)
        self.assertIn("jsonb_to_recordset",CURRENT_OFFICIAL_LISTED_CTE)
        for sql in (LATEST_RANKING_SQL,LATEST_MODEL_SQL,TRAINING_SQL,
                    ADJUSTED_EVALUATION_SQL):
            self.assertIn("JOIN official_current_listed active",sql)
            self.assertIn("active.stock_id=s.stock_id",sql)
            self.assertIn("JOIN public.stock_master sm",sql)
            self.assertIn("public.official_issuer_weekly_snapshots",sql)
            self.assertIn("public.official_issuer_snapshot_corrections",sql)
            self.assertNotIn("UPDATE public.",sql.upper())
            self.assertNotIn("INSERT INTO",sql.upper())
            self.assertNotIn("DELETE FROM",sql.upper())

    def test_real_official_latest_master_only_exclusion_is_explicit(self):
        proof=m.verify(totals(),[{
            "market":"twse","stock_id":"1589","stock_name":"永冠-KY"}])
        self.assertEqual(proof["master_stocks"],1991)
        self.assertEqual(proof["current_official_stocks"],1990)
        self.assertEqual(proof["selectable_officially_listed_master_stocks"],1990)
        self.assertEqual(proof["master_only_stocks_excluded_from_new_rankings"],1)
        self.assertEqual(proof["sample_excluded_stocks"][0]["stock_id"],"1589")
        self.assertTrue(proof["historical_scores_and_raw_prices_preserved"])
        self.assertTrue(proof["historical_survivorship_bias_explicit"])
        self.assertFalse(proof["historical_unbiased_alpha_claim_allowed"])
        self.assertFalse(proof["live_trading_approved"])
        self.assertEqual(proof["database_writes"],0)

    def test_missing_or_unavailable_official_snapshot_fails_closed(self):
        for invalid in (
            {**totals(),"last_current_official_observed_at":None,
             "official_current_listing_count":0,
             "matched_current_exchange_issuers":0},
            {**totals(),"official_current_listing_count":0},
            {**totals(),"master_only_excluded":0},
            {**totals(),"matched_current_exchange_issuers":False},
            {**totals(),"official_missing_from_current_master":1},
        ):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                m.verify(invalid,[])
        with self.assertRaises(ValueError):
            m.verify(totals(),[{"market":"bogus","stock_id":"1589"}])

    def test_actual_neon_verification_sql_uses_readonly_snapshot_only(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def dispatch(sql):
            out=MagicMock()
            if sql==m.AUDIT_SQL:out.fetchone.return_value=totals()
            if sql==m.EXCLUSIONS_SQL:
                out.fetchall.return_value=[{
                    "market":"twse","stock_id":"1589","stock_name":"永冠-KY"}]
            return out
        conn.execute.side_effect=dispatch
        with patch.object(m.psycopg,"connect",return_value=conn) as db:
            proof=m.inspect("existing-protected-url")
        self.assertEqual(proof["master_only_stocks_excluded_from_new_rankings"],1)
        self.assertIn("default_transaction_read_only=on",
                      db.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ READ ONLY",
                      conn.execute.call_args_list[0].args[0])

    def test_daily_line_report_top_research_display_filters_current_official(self):
        s=Path(send_line_report.__file__).read_text(encoding="utf-8")
        self.assertIn("JOIN official_current_listed active",s)
        self.assertIn("active.stock_id=p.stock_id",s)
        self.assertIn("CURRENT_OFFICIAL_LISTED_CTE",s)
        self.assertNotIn("push",m.AUDIT_SQL.lower())

    def test_workflow_does_not_send_line_or_write_data_or_buy_services(self):
        wf=(ROOT/".github/workflows/current-official-listed-only-audit.yml").read_text()
        self.assertIn(".github/current-official-listed-only-20261122.txt",wf)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",wf)
        self.assertIn("current_listed_only_audit.py",wf)
        self.assertIn("  workflow_dispatch:",wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("--apply",wf)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN",wf)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",wf)
