"""Synthetic exact-core parity and actual raw factor pilot; no owner credentials."""
from datetime import date,timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch
from scripts import twse_owner_early_economic_factor_pilot_readonly as m

def fixture():
    end=m.CUTOFF
    days=[]
    while len(days)<274:
        if end.weekday()<5:
            days.append(end)
        end-=timedelta(days=1)
    days=sorted(days)
    roster=["2330","1101","2327","2603","2317"]
    def bar(s,d,i,tag):
        p=Decimal(100)+Decimal(i)/100
        return dict(market="twse",stock_id=s,trade_date=d,source=tag,
                    open=p,high=p+1,low=p-1,close=p,volume=100000+i)
    a=[bar(s,d,i,"TWSE_MI_INDEX_ALLBUT0999") for s in roster for i,d in enumerate(days)
       if s!="2317" or i!=150]
    b=[bar(s,days[100],100,"TWSE_STOCK_DAY") for s in roster]
    b[1]["close"]+=Decimal("0.01")
    b[2]["high"]=Decimal("NaN")
    return roster,a,b,days

class EconomicPilotTests(unittest.TestCase):
    def test_actual_calculators_and_quarantine(self):
        r=m.factor_pilot(*fixture())
        self.assertEqual(r["overlap_source_keys"],5)
        self.assertEqual(r["exact_core_ohlcv_overlap_keys"],3)
        self.assertEqual(r["conflicting_valid_ohlcv_overlap_keys"],1)
        self.assertEqual(r["invalid_neon_overlap_keys"],1)
        self.assertEqual(r["raw_factor_pilot_accepted_stocks"],2)
        self.assertEqual(r["excluded_stocks_by_primary_reason"],{
            "incomplete_last_240_observed_market_dates":1,
            "invalid_neon_ohlcv":1,"overlap_ohlcv_conflict":1})
        self.assertFalse(r["corporate_actions_adjusted"])
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertNotIn("2330",str(r))

    def test_order_invariant_and_reject_duplicate(self):
        roster,a,b,days=fixture()
        self.assertEqual(m.factor_pilot(roster,a,b,days),m.factor_pilot(roster[::-1],a[::-1],b[::-1],days[::-1]))
        with self.assertRaises(ValueError):
            m.factor_pilot(roster,a,b+[b[0]],days)
        with self.assertRaises(ValueError):
            m.factor_pilot(roster+["1589"],a,b,days)

    def test_invalid_archive_is_hard_failure(self):
        roster,a,b,days=fixture()
        a[0]["volume"]=-1
        with self.assertRaises(ValueError):
            m.factor_pilot(roster,a,b,days)

    def test_conflict_does_not_call_factor_calculator_for_excluded_issuer(self):
        roster,a,b,days=fixture()
        with patch.object(m,"build_research_features",wraps=m.build_research_features) as calc:
            m.factor_pilot(roster,a,b,days)
        self.assertEqual({c.kwargs["stock_id"] for c in calc.call_args_list},{"2330","2603"})
