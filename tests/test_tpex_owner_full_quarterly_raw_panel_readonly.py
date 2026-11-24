from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch
from scripts import tpex_owner_full_quarterly_raw_panel_readonly as m

class TpexPanelTests(unittest.TestCase):
    def fixture(self):
        days=set();d=m.depth.START
        while d<m.depth.END:
            if d.weekday()<5:
                days.add(d)
            d+=timedelta(days=1)
        raw={};counts=[]
        for sid in ("6488","8299"):
            raw[sid]=[]
            for i,d in enumerate(sorted(days)):
                p=Decimal(100)+Decimal(i%41)/100
                legacy=sid=="6488" and d.year<=2023
                raw[sid].append((d,sid,"TPEX_TRADING_STOCK" if legacy else "TPEX_DATED_OTC_EW",p,p+1,p-1,p,100 if legacy else 100000))
            for y in range(2021,2027):
                n=sum(r[0].year==y for r in raw[sid])
                counts.append((sid,y,n,n))
        return ["6488","8299"],raw,days,counts

    def test_real_engine_normalized_volume_parity(self):
        roster,raw,days,counts=self.fixture()
        with patch.object(m,"BATCH",1):
            report,features,receipts=m.panel(roster,raw,days,counts)
        self.assertEqual(report["accepted_feature_rows"],34)
        self.assertEqual(report["accepted_feature_values"],408)
        self.assertEqual(len(receipts),2)
        for a,b in zip(features[::2],features[1::2]):
            self.assertEqual(a["feature_vector"],b["feature_vector"])
            self.assertEqual(a["market"],"tpex")
            self.assertEqual(a["signal_date"],b["signal_date"])
        self.assertGreater(report["original_source_row_counts"]["TPEX_TRADING_STOCK"],0)
        self.assertFalse(report["corporate_actions_adjusted"])

    def test_missing_market_day_and_future_invalid(self):
        roster,raw,days,counts=self.fixture()
        missing=m.SIGNALS[0]
        days.remove(missing)
        for sid in roster:
            raw[sid]=[r for r in raw[sid] if r[0]!=missing]
        counts=[(s,y,n-1,n-1) if y==missing.year else (s,y,n,n) for s,y,n,_ in counts]
        r,_,_=m.panel(roster,raw,days,counts)
        self.assertEqual(r["signal_date_outcomes"][0]["excluded"],{"no_observed_market_source_date":2})
        roster,raw,days,counts=self.fixture()
        raw["6488"]=[(*r[:7],-1) if r[0]==m.SIGNALS[-1] else r for r in raw["6488"]]
        r,_,_=m.panel(roster,raw,days,counts)
        self.assertEqual(r["signal_date_outcomes"][0]["accepted"],2)
        self.assertEqual(r["signal_date_outcomes"][-1]["accepted"],1)
        with self.assertRaises(ValueError):
            m.panel(roster,dict(raw,**{"6488":raw["6488"]+[raw["6488"][0]]}),days,counts)
