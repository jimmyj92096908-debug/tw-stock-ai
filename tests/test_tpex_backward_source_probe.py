"""No writes, no fabricated dates and exact source-close matching."""
from datetime import date
import os
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from scripts import tpex_backward_source_probe as m

def srcday(day,close=100):
    return {"stock_id":"4183","trade_date":day,"open":close,"high":close+2,
            "low":close-2,"close":close,"volume":100,"turnover":10000,
            "change":0,"transactions":1,"source":"TPEX_TRADING_STOCK"}

class TPExBackwardSourceProbeTests(unittest.TestCase):
    def test_original_and_source_exact_same_date_proof(self):
        rows=[srcday("2026-07-07"),srcday("2026-07-08")]
        saved=[{"trade_date":date(2026,7,7),"close":100},
               {"trade_date":date(2026,7,8),"close":100}]
        x=m.compare_month("4183",date(2026,7,1),rows,saved)
        self.assertEqual(x["identical_closes"],2)
        self.assertTrue(x["anchor_verified"])
        self.assertFalse(m.compare_month("4183",date(2026,7,1),rows,
                                         saved[:1])["anchor_verified"])
        y=m.compare_month("4183",date(2026,7,1),rows,
                          [{"trade_date":date(2026,7,7),"close":101},saved[1]])
        self.assertEqual(y["different_closes"],1)
        self.assertFalse(y["anchor_verified"])
        z=m.compare_month("4183",date(2026,7,1),[],saved)
        self.assertEqual(z["same_date_overlap"],0)
        self.assertFalse(z["anchor_verified"])

    def test_source_wrong_month_cannot_fake_match(self):
        with self.assertRaises(ValueError):
            m.compare_month("4183",date(2026,7,1),
                            [srcday("2026-11-20")],[])

    def test_four_only_and_neon_read_only(self):
        self.assertEqual(len(m.STOCKS)*len(m.MONTHS),m.MAX_CALLS)
        self.assertEqual(m.MAX_CALLS,4)
        self.assertEqual(m.MONTHS,(date(2026,7,1),date(2026,11,1)))
        self.assertNotIn("INSERT INTO",m.SAVED_SQL.upper())
        self.assertNotIn("UPDATE ",m.SAVED_SQL.upper())
        self.assertNotIn("DELETE ",m.SAVED_SQL.upper())
        with self.assertRaises(ValueError):
            m.run("",sleep_seconds=0)

    def test_workflow_exact_marker_no_write_schedule(self):
        workflow=(Path(__file__).resolve().parents[1]/
            ".github/workflows/tpex-backward-official-source-probe.yml").read_text()
        self.assertIn(''.join(["git diff --name-only --diff-filter=A HEAD^ HEAD"]),workflow)
        self.assertIn(".github/tpex-long-history-source-probe-20261121.txt",workflow)
        self.assertNotIn("  schedule:",workflow)
        self.assertIn("tpex_backward_source_probe.py",workflow)
        self.assertNotIn("STOCK_TPEX_LONG_HISTORY_ENABLED",workflow)
