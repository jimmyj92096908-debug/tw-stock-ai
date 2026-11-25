from datetime import date,timedelta
import unittest
from scripts import owner_quarterly_chip_vintage_coverage_readonly as m

class ChipCoverageTests(unittest.TestCase):
    def test_present_vs_retained(self):
        d=date(2026,11,20);last=d-timedelta(days=1)
        rows=[("institutional","2330",20,last,0,None),
              ("margin","2330",2,last,2,last),
              ("tdcc","2330",2,last,2,last),
              ("insider","2330",1,last,0,None)]
        r=m.classify(["2330","2317"],d,rows)
        self.assertEqual(r["present_all_four_candidates"],1)
        self.assertEqual(r["retained_all_four_candidates"],0)
        self.assertEqual(r["retained_candidate_weight_at_least_50"],1)
        self.assertEqual(r["retained_before_signal_candidates"]["institutional"],0)
        self.assertEqual(r["candidate_rows"],2)

    def test_stale_and_future_rejected(self):
        d=date(2026,11,20);old=d-timedelta(days=8)
        r=m.classify(["2330"],d,[("institutional","2330",20,old,20,old)])
        self.assertEqual(r["present_source_maturity_candidates"]["institutional"],0)
        for rows in (
            [("margin","2330",2,d,2,d)],
            [("margin","2330",1,old,2,old)],
            [("margin","2317",2,old,2,old)],
            [("margin","2330",2,old,2,old)]*2,
        ):
            with self.assertRaises(ValueError):
                m.classify(["2330"],d,rows)

    def test_sql_conservative_bounds(self):
        self.assertEqual(m.SQL.count("retrieved_at <"),4)
        self.assertEqual(m.SQL.count("AT TIME ZONE 'Asia/Taipei'"),4)
        self.assertIn("COUNT(DISTINCT p.holder_range)=15",m.SQL)
        self.assertIn("p.pledged_shares<=p.share_count",m.SQL)
        self.assertNotIn("INSERT",m.SQL.upper())
