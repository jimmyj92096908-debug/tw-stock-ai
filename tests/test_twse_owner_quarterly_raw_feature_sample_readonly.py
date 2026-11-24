"""Offline synthetic calendar and strict per-signal prefix checks."""
from datetime import date,timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch
from scripts import twse_owner_quarterly_raw_feature_sample_readonly as m

def fixture():
    roster=[str(2000+i) for i in range(24)]
    selected=m.sample_roster(roster)
    calendar=set()
    d=m.depth.START
    while d<m.depth.END:
        if d.weekday()<5:
            calendar.add(d)
        d+=timedelta(days=1)
    days=sorted(calendar)
    sid=selected[0]
    rows=[]
    for i,d in enumerate(days):
        p=Decimal(100)+Decimal(i%41)/100
        rows.append(dict(market="twse",stock_id=sid,trade_date=d,source="TWSE_STOCK_DAY",
                         open=p,high=p+1,low=p-1,close=p,volume=100000+i))
    return roster,selected,calendar,{sid:rows}

class QuarterlySampleTests(unittest.TestCase):
    def test_sample_order_and_exclusion(self):
        roster,selected,_,_=fixture()
        self.assertEqual(selected,m.sample_roster(roster[::-1]))
        with self.assertRaises(ValueError):
            m.sample_roster(roster+["1589"])
        with self.assertRaises(ValueError):
            m.sample_roster(roster+[roster[0]])

    def test_real_calculator_prefix_and_future_perturbation(self):
        _,selected,calendar,groups=fixture()
        signals=m.signal_schedule(calendar)
        self.assertEqual(len(signals),17)
        with patch.object(m,"build_research_features",wraps=m.build_research_features) as calc:
            summary,features=m.calculate_sample(selected,groups,set(),calendar,signals)
        self.assertEqual(summary["accepted_feature_rows"],17)
        self.assertEqual(summary["accepted_feature_values"],204)
        self.assertEqual(len(calc.call_args_list),17)
        for call in calc.call_args_list:
            prefix=call.args[0];cutoff=call.kwargs["cutoff"]
            self.assertEqual(max(r["trade_date"] for r in prefix),cutoff)
            self.assertTrue(all(r["trade_date"]<=cutoff for r in prefix))
        modified={selected[0]:[dict(r,close=r["close"]+Decimal("0.5"))
                    if r["trade_date"]>signals[0] else dict(r) for r in groups[selected[0]]]}
        _,changed=m.calculate_sample(selected,modified,set(),calendar,signals)
        self.assertEqual(features[0],changed[0])
        self.assertNotEqual(features[-1]["prefix_source_sha256"],changed[-1]["prefix_source_sha256"])
        self.assertFalse(summary["forward_labels_created"])
        self.assertEqual(summary["model_release"],"BLOCKED")

    def test_gap_and_invalid_issuer_quarantine(self):
        _,selected,calendar,groups=fixture()
        signals=m.signal_schedule(calendar)
        sid=selected[0]
        groups[sid]=[r for r in groups[sid] if r["trade_date"]!=signals[0]]
        _,features=m.calculate_sample(selected,groups,set(),calendar,signals)
        self.assertNotIn(signals[0].isoformat(),{r["signal_date"] for r in features})
        summary,features=m.calculate_sample(selected,groups,{sid},calendar,signals)
        self.assertEqual(features,[])
        self.assertEqual(summary["signal_date_outcomes"][0]["excluded"]["issuer_invalid_late_ohlcv"],1)
        with self.assertRaises(ValueError):
            m.calculate_sample(selected,groups,set(),calendar,signals[:-1])
