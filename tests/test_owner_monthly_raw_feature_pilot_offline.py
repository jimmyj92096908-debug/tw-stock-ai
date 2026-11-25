from datetime import date,timedelta
from decimal import Decimal
import unittest
from scripts import owner_monthly_raw_feature_pilot_offline as m
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as merge
from scripts import twse_owner_quarterly_raw_feature_sample_readonly as q

class MonthlyPilotTests(unittest.TestCase):
    def fixture(self):
        days=set()
        d=q.depth.START
        while d<=m.CUTOFF:
            if d.weekday()<5:
                days.add(d)
            d+=timedelta(days=1)
        for value in merge.DATES:
            anchor=date.fromisoformat(value)
            days={d for d in days if not (d.year==anchor.year and d.month==anchor.month and d>anchor)}
        rows=[]
        for i,d in enumerate(sorted(days)):
            p=Decimal(100)+Decimal(i%31)/100
            rows.append({"market":"twse","stock_id":"2330","trade_date":d,
                "open":p,"high":p+1,"low":p-1,"close":p,"volume":100000,"source":"TWSE_STOCK_DAY"})
        return days,{"2330":rows}

    def test_schedule_and_exact_quarterly_replay(self):
        days,groups=self.fixture()
        schedule=q.monthly_signal_schedule(days)
        self.assertEqual(len(schedule),48)
        self.assertEqual(schedule[-1],m.CUTOFF)
        quarterly=[date.fromisoformat(d) for d in merge.DATES]
        _,anchors=q.calculate_cohort(["2330"],groups,{},days,quarterly)
        r,rows=m.monthly_pilot(["2330"],groups,{},days,days,anchors,market="twse")
        self.assertEqual(r["requested_signal_dates"],48)
        self.assertEqual(len(rows),48)
        self.assertEqual(r["quarterly_anchor_rows_replayed"],17)
        self.assertFalse(r["forward_labels_created"])
        changed=[dict(x) for x in anchors]
        changed[0]["feature_vector"]=[123.0]*12
        with self.assertRaises(ValueError):
            m.monthly_pilot(["2330"],groups,{},days,days,changed,market="twse")

    def test_missing_month_and_market_date(self):
        days,groups=self.fixture()
        with self.assertRaises(ValueError):
            q.monthly_signal_schedule({d for d in days if (d.year,d.month)!=(2024,5)})
        schedule=q.monthly_signal_schedule(days)
        missing=schedule[5]
        tpex_days=days-{missing}
        tpex_groups={"2330":[dict(r,market="tpex",source="TPEX_DATED_OTC_EW") for r in groups["2330"] if r["trade_date"]!=missing]}
        report,_=q.calculate_cohort(["2330"],tpex_groups,{},tpex_days,schedule,
            market="tpex",schedule="monthly",reference_calendar=days)
        self.assertEqual(report["signal_date_outcomes"][5]["excluded"],{"no_observed_market_source_date":1})

    def test_budget_not_data(self):
        r=m.schedule_budget()
        self.assertEqual(r["maximum_potential_mature_dates"],47)
        self.assertFalse(r["new_monthly_features_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")
