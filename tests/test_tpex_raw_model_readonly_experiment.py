"""Actual-free READ ONLY Neon source adapter to exploratory raw-only AI dataset."""
from datetime import date,timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import tpex_raw_model_readonly_experiment as m

def source(sid):
    out=[]
    for i in range(320):
        day=date(2025,1,1)+timedelta(days=i)
        x=80+i*0.08+int(sid)%9
        out.append({"market":"tpex","stock_id":sid,"trade_date":day,
                    "open":x-0.1,"high":x+2,"low":x-2,"close":x,
                    "volume":int(1000+i*2),"source":"TPEX_DATED_OTC_EW"})
    return out

class RealRawFactorReadOnlyAdapterTests(TestCase):
    def test_neon_snapshot_single_readonly_transaction_and_no_persist(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        histories={sid:source(sid) for sid in m.PROTOTYPE_STOCKS}
        dates=[histories[m.PROTOTYPE_STOCKS[0]][i]["trade_date"]
               for i in range(250,310)]
        signals=list(reversed(dates[-50:]))
        def execute(sql,args=None):
            q=MagicMock()
            if sql==m.MASTER_SQL:
                q.fetchone.return_value={"registered":len(m.PROTOTYPE_STOCKS)}
            elif sql==m.PRICE_SQL:
                q.fetchall.return_value=histories[args[0]]
            elif sql==m.SIGNALS_SQL:
                q.fetchall.return_value=[{"trade_date":x} for x in signals]
            return q
        conn.execute.side_effect=execute
        # The actual 60 most recent sample dates produce 60 whole cohorts, but
        # many final sessions have immature forward labels; research blocks.
        with patch.object(m.psycopg,"connect",return_value=conn) as connected:
            out=m.execute("existing-url",label_cutoff=date(2025,12,1),
                         test_start=date(2025,10,20),max_signals=50)
        self.assertTrue(out["database_read_only"])
        self.assertTrue(out["no_new_persistent_factor_rows"])
        self.assertTrue(out["production_tw_factor_ridge_1_unchanged"])
        self.assertFalse(out["model_release_approved"])
        self.assertFalse(out["live_trading_approved"])
        self.assertGreater(out["accepted_full_cohort_dates"],0)
        self.assertIn("default_transaction_read_only=on",
                      connected.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ READ ONLY",conn.execute.call_args_list[0].args[0])
        self.assertIn("ORDER BY trade_date DESC LIMIT %s",m.PRICE_SQL)
        self.assertIn("ORDER BY trade_date",m.PRICE_SQL)
        self.assertNotIn("UPDATE",m.PRICE_SQL.upper())
        self.assertNotIn("DELETE",m.PRICE_SQL.upper())

    def test_frozen_six_stock_membership_cannot_be_auto_replaced(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={"registered":5}
        with patch.object(m.psycopg,"connect",return_value=conn):
            with self.assertRaises(RuntimeError):
                m.execute("existing-url",label_cutoff=date(2026,11,20),
                          test_start=date(2026,10,30))
        with self.assertRaises(ValueError):
            m.execute("",label_cutoff=date(2026,11,20),
                      test_start=date(2026,10,30))
        with self.assertRaises(ValueError):
            m.execute("url",label_cutoff=date(2026,11,20),
                      test_start=date(2026,11,21))
        with self.assertRaises(ValueError):
            m.execute("url",label_cutoff=date(2026,11,20),
                      test_start=date(2026,10,30),max_signals=101)

    def test_workflow_runs_actual_neon_research_without_any_data_write(self):
        wf=(Path(__file__).resolve().parents[1]/
            ".github/workflows/tpex-raw-asof-ai-research.yml").read_text()
        marker=".github/tpex-raw-asof-ai-research-20261121.txt"
        self.assertIn(marker,wf)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",wf)
        self.assertIn("  push:",wf)
        self.assertIn("  workflow_dispatch:",wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("--apply",wf)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",wf)
        self.assertIn("tpex_raw_model_readonly_experiment.py",wf)
        self.assertIn("tests.test_raw_factor_walkforward",wf)
