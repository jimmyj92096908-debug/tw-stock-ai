"""Synthetic exact-key replay, no production connection or archive credentials."""
from collections import Counter
from datetime import date,timedelta
import unittest
from unittest.mock import patch
from scripts import twse_owner_five_year_source_depth_readonly as m
from tests.test_twse_2021_28day_aes_neon_stockdate_union_readonly import frozen_owner_2021
from tests.test_twse_2022_aes_neon_eligible_density_readonly import inputs
from scripts.twse_2022_aes_neon_eligible_density_readonly import classify_current_stock_source_absences

class SourceDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,roster,aes21,_=frozen_owner_2021()
        _,_,_,r2,aes22,bulk,n22,_=inputs()
        assert roster==r2
        n21=[(d,s,"TWSE_STOCK_DAY") for i,d in enumerate(sorted(aes21))
             for s in roster[:(20 if i<20 else 19)]]
        early=n21+n22
        k21={(d,s) for d,ss in aes21.items() for s in ss}
        k22={(d,s) for d,ss in aes22.items() for s in ss}
        union=k22|{(d,s) for d,s,t in n22}
        cal=sorted({d for d,s in union});idx={d:i for i,d in enumerate(cal)}
        counts=Counter();first={};last={}
        for d,s in sorted(union):
            counts[s]+=1;first.setdefault(s,idx[d]);last[s]=idx[d]
        c21=Counter(s for d,s in k21)
        h=Counter(str(c21[s]) for s in roster)
        late=[(s,y,240,240) for s in roster[:800] for y in range(2023,2027)]
        nc=Counter(s for d,s,t in early)
        vals=[nc[s]+(960 if s in roster[:800] else 0) for s in roster]
        # Independent explicit bin definitions.
        cuts=[(0,0),(1,59),(60,239),(240,479),(480,999),(1000,2000)]
        names=["stock_days0","stock_days1_59","stock_days60_239","stock_days240_479","stock_days480_999","stock_days1000_plus"]
        base={"market":{"twse":{"yearly_neon_source_observations":[{"year":y,"neon_stored_valid_source_stock_bars":800*240} for y in range(2023,2027)],"per_stock_5year_neon_valid_days_distribution":{k:sum(lo<=v<=hi for v in vals) for k,(lo,hi) in zip(names,cuts)}}}}
        expected={"twse_2021_union_observed_keys":len(k21),"twse_2022_union_observed_keys_from_absence_conservation":len(union),"twse_neon_only_baseline_stock_date_keys":sum(vals),"conditional_twse_baseline_replacement_keys":len(k21)+len(union)+800*960}
        report21={"scope":m.overlay.S21,"schema_version":1,"production_neon_writes":0,"line_messages_sent":0,"model_release":"BLOCKED","current_stock_source_day_count_histogram":dict(h)}
        report22={"current_listed_source_date_observation_absence_signatures":classify_current_stock_source_absences(roster,counts,first,last,source_day_count=246)}
        cls.args=(roster,early,late,k21,k22,set(aes21),set(aes22))
        cls.kw=dict(expected=expected,baseline=base,report21=report21,report22=report22)

    def test_exact_conservation_and_depth(self):
        r=m.depth_summary(*self.args,**self.kw)
        self.assertEqual(r["merged_source_keys"],self.kw["expected"]["conditional_twse_baseline_replacement_keys"])
        self.assertEqual(r["merged_at_least_1000"],800)
        self.assertEqual(sum(r["merged_depth_distribution"].values()),1092)
        self.assertFalse(r["factor_values_recomputed"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_duplicate_and_wrong_year_rejected(self):
        for index,value in ((1,[*self.args[1],self.args[1][0]]),(2,[*self.args[2],self.args[2][0]]),(2,[("1589",2023,240,240),*self.args[2]])):
            changed=list(self.args);changed[index]=value
            with self.assertRaises(ValueError):
                m.depth_summary(*changed,**self.kw)
