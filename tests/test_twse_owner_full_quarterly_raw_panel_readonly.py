from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch
from scripts import twse_owner_full_quarterly_raw_panel_readonly as m
from tests.test_twse_owner_quarterly_raw_feature_sample_readonly import fixture

class FullPanelTests(unittest.TestCase):
    def test_real_engine_sample_parity_and_batch_partition(self):
        roster,selected,calendar,groups=fixture()
        sid=selected[0]
        early={sid:[r for r in groups[sid] if r["trade_date"]<m.depth.EARLY_END]}
        late={sid:[tuple(r[k] for k in m.early.COLS) for r in groups[sid] if r["trade_date"]>=m.depth.EARLY_END]}
        counts=[]
        for y in range(2023,2027):
            n=sum(r[0].year==y for r in late[sid])
            counts.append((sid,y,n,n))
        signals=m.q.signal_schedule(calendar)
        expected,rows=m.q.calculate_sample(selected,groups,{},calendar,signals)
        with patch.object(m,"BATCH",7):
            report,actual,receipts=m.panel(roster,early,late,calendar,counts,signals)
        self.assertEqual(actual,rows)
        self.assertEqual(report["sample_replay_sha256"],m.fingerprint(rows))
        self.assertEqual(report["batch_count"],4)
        self.assertEqual(sum(r["issuer_count"] for r in receipts),24)
        self.assertEqual(report["candidate_stock_signal_pairs"],408)
        self.assertEqual(report["accepted_feature_rows"],17)
        self.assertEqual(report["model_release"],"BLOCKED")
        self.assertFalse(report["forward_labels_created"])
        with self.assertRaises(ValueError):
            m.process_batch([sid],early,{sid:late[sid]+[late[sid][0]]},calendar,counts,signals)

    def test_budget(self):
        self.assertEqual(m.read_budget([("2330",2023,200,200)],200),200)
        for n in (0,1000001):
            with self.assertRaises(ValueError):
                m.read_budget([("2330",2023,n,n)],n)
        with self.assertRaises(ValueError):
            m.read_budget([("2330",2023,200,200)],201)
