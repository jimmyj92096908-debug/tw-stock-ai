from datetime import date,timedelta
from decimal import Decimal
import unittest
from scripts import owner_five_stock_aes_direct_factor_research_offline as b
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m

class BridgeTests(unittest.TestCase):
    def fixture(self):
        d=date(2023,1,1);days=[]
        anchors={(date.fromisoformat(x).year,date.fromisoformat(x).month):date.fromisoformat(x) for x in m.DATES[1:]}
        while d<=b.CUTOFF:
            if d.weekday()<5 and d<=anchors.get((d.year,d.month),b.CUTOFF):days.append(d)
            d+=timedelta(days=1)
        ids=("1101","2308","2317","2330","2454")
        rows=[]
        for i,d in enumerate(days):
            for sid in ids:
                p=Decimal(100)+Decimal(i%31)/100
                rows.append({"market":"twse","stock_id":sid,"trade_date":d,"source":"TWSE_STOCK_DAY",
                    "open":p,"high":p+1,"low":p-1,"close":p,"volume":100000})
        return ids,rows
    def test_actual_factor_engine_and_cutoff(self):
        ids,rows=self.fixture()
        report,features=b.compute(ids,rows,[],[])
        self.assertEqual(report["requested_signal_dates"],47)
        self.assertGreater(report["accepted_feature_rows"],100)
        self.assertEqual(report["comparisons"]["late_vs_aes_join_vector_equal"],len(features))
        self.assertFalse(report["exact_prior_quarterly_panel_reproduced"])
        self.assertEqual(report["model_release"],"BLOCKED")
        with self.assertRaises(ValueError):b.compute(ids,rows+[rows[0]],[],[])
