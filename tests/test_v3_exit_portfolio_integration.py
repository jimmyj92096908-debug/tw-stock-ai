"""Synthetic integration tests for OHLC exit stress and cash settlement."""
import unittest
from copy import deepcopy

from src.v3_portfolio_accounting import simulate_portfolio


class ExitPortfolioTests(unittest.TestCase):
    def rows(self):
        dates=["2024-06-03","2024-06-04","2024-06-05",
               "2024-06-06","2024-06-07","2024-06-10"]
        return [{"date":d,"bars":{"2301":{"market":"TWSE",
                 "currently_listed":True,"corporate_action_clear":True,
                 "open":10,"high":10,"low":10,"close":10,
                 "buy_eligible":True,"sell_eligible":True,
                 "buy_capacity_shares":100000,"sell_capacity_shares":100000}},
                 "corporate_actions":[],
                 "close_targets":({"2301":0.1} if i==0 else None)}
                for i,d in enumerate(dates)]

    def set_bar(self, rows, index, op, hi, lo, close, **extra):
        rows[index]["bars"]["2301"].update(open=op,high=hi,low=lo,close=close,**extra)

    def run_case(self, rows, **kw):
        args=dict(exit_stress_mode=True,commission=0,sell_tax=0,slippage=0)
        args.update(kw)
        return simulate_portfolio(rows,**args)

    def test_gap_blocked_partial_exit_no_same_day_reentry(self):
        rows=self.rows()
        self.set_bar(rows,2,8,8,8,8,sell_eligible=False)
        self.set_bar(rows,3,7,7,7,7,sell_capacity_shares=4000)
        self.set_bar(rows,4,6,6,6,6)
        rows[1]["close_targets"]={"2301":0.1}
        rows[2]["close_targets"]={"2301":0.1}
        rows[3]["close_targets"]={"2301":0.1}
        r=self.run_case(rows)
        self.assertEqual([x["side"] for x in r["fills"]],["BUY","SELL","SELL"])
        self.assertEqual([x["shares"] for x in r["fills"]],[10000,4000,6000])
        self.assertEqual(r["path"][2]["pending_exit_stocks"],["2301"])
        self.assertEqual(r["path"][3]["holdings"]["2301"],6000)
        self.assertEqual(r["path"][3]["available_cash"],900000)
        self.assertEqual(r["path"][4]["unsettled_sale_proceeds"],64000)
        self.assertEqual(r["path"][5]["available_cash"],928000)
        self.assertAlmostEqual(r["closed_position_episodes"][0]["net_return"],-0.36)
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_entry_day_dual_touch_uses_stop_first(self):
        rows=self.rows()
        self.set_bar(rows,1,10,12,9,11)
        r=self.run_case(rows)
        self.assertEqual(r["fills"][1]["reason"],"STOP_FIRST")
        self.assertEqual(r["fills"][0]["date"],r["fills"][1]["date"])
        self.assertAlmostEqual(r["fills"][1]["fill"],9.5)

    def test_trailing_uses_previous_session_high(self):
        rows=self.rows()
        self.set_bar(rows,1,10,10.8,9.8,10.7)
        self.set_bar(rows,2,10.6,10.7,10.1,10.3)
        r=self.run_case(rows)
        self.assertEqual(r["fills"][1]["date"],rows[2]["date"])
        self.assertAlmostEqual(r["fills"][1]["fill"],10.26)

    def test_cash_dividend_adjusts_exit_levels(self):
        rows=self.rows()
        rows[2]["corporate_actions"]=[dict(event_id="e1",stock_id="2301",
            market="TWSE",currently_listed=True,terms_verified=True,
            source_sha256="a"*64,effective_session="2024-06-05",
            public_date="2024-06-03",kind="CASH_DIVIDEND",
            cash_per_share="2",credit_session="2024-06-10")]
        rows[2]["bars"]["2301"]["corporate_action_clear"]=False
        for i in range(2,len(rows)):
            self.set_bar(rows,i,8,8,8,8)
        r=self.run_case(rows,corporate_action_mode=True)
        self.assertEqual(len(r["fills"]),1)
        self.assertEqual(r["open_position_count"],1)
        self.assertAlmostEqual(r["net_marked_return"],0)
        self.assertEqual(r["path"][2]["gross_dividend_receivable"],20000)

    def test_unknown_buy_capacity_and_invalid_bars(self):
        rows=self.rows()
        rows[1]["bars"]["2301"].pop("buy_capacity_shares")
        self.assertEqual(self.run_case(rows)["fills"],[])
        for patch in ({"low":11},{"sell_eligible":1},{"buy_capacity_shares":-1}):
            rows=self.rows()
            rows[1]["bars"]["2301"].update(patch)
            with self.assertRaises(ValueError):
                self.run_case(rows)


if __name__=="__main__":
    unittest.main()
