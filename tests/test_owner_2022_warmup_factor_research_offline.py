from datetime import date
from decimal import Decimal
import unittest
from scripts import owner_2022_warmup_factor_research_offline as w

class WarmupMergeTests(unittest.TestCase):
    def bar(self,day,source,close="100"):
        return dict(market="twse",stock_id="1101",trade_date=day,source=source,
                    open=Decimal("100"),high=Decimal("102"),low=Decimal("98"),
                    close=Decimal(close),volume=1000)
    def test_exact_overlap_and_cutoff(self):
        a=self.bar(date(2022,1,3),"TWSE_MI_INDEX_ALLBUT0999")
        d=dict(a,source="TWSE_STOCK_DAY")
        n=self.bar(date(2022,1,4),"TWSE_STOCK_DAY")
        future=self.bar(date(2026,11,23),"TWSE_STOCK_DAY")
        r,g,c=w.merge_warmup(("1101",),[a],[d,n],[future])
        self.assertEqual(r["aes_direct_overlap_rows"],1)
        self.assertEqual(r["new_2022_source_rows"],1)
        self.assertEqual(r["post_cutoff_rows_excluded"],1)
        self.assertEqual(len(g["1101"]),2)
        self.assertEqual(len(c),2)
        self.assertIn(a,g["1101"])
    def test_conflict_and_absence_fail_closed(self):
        a=self.bar(date(2022,1,3),"TWSE_MI_INDEX_ALLBUT0999")
        d=dict(a,source="TWSE_STOCK_DAY",close=Decimal("101"))
        r,g,c=w.merge_warmup(("1101",),[a],[d],[])
        self.assertEqual(r["aes_direct_conflicting_rows"],1)
        self.assertIsNone(g)
        r,g,c=w.merge_warmup(("1101",),[a],[],[])
        self.assertEqual(r["aes_2022_rows_missing_from_direct"],1)
        self.assertIsNone(g)
        with self.assertRaises(ValueError):w.merge_warmup(("1101",),[a,a],[d],[])
