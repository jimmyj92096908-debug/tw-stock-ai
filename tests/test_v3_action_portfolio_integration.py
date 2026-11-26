"""Synthetic integration checks for corporate-action portfolio accounting."""
import unittest
from copy import deepcopy
from src.v3_portfolio_accounting import simulate_portfolio


class ActionPortfolioTests(unittest.TestCase):
    def sessions(self):
        dates=["2024-06-03","2024-06-04","2024-06-05",
               "2024-06-06","2024-06-07","2024-06-10"]
        return [{"date":d,"bars":{"2301":{"market":"TWSE",
                 "currently_listed":True,"corporate_action_clear":True,
                 "open":10,"close":10}},"corporate_actions":[],
                 "close_targets":({"2301":0.1} if i==0 else None)}
                for i,d in enumerate(dates)]

    def action(self, **kw):
        a=dict(event_id="e1",stock_id="2301",market="TWSE",
               currently_listed=True,terms_verified=True,source_sha256="a"*64,
               effective_session="2024-06-05",public_date="2024-06-03",
               kind="CASH_DIVIDEND",cash_per_share="2",credit_session="2024-06-10")
        a.update(kw)
        return a

    def install(self, rows, action, new_price):
        rows[2]["corporate_actions"]=[action]
        rows[2]["bars"]["2301"]["corporate_action_clear"]=False
        for row in rows[2:]:
            row["bars"]["2301"].update(open=new_price,close=new_price)
        return rows

    def run_case(self, rows, **kw):
        args=dict(commission=0,sell_tax=0,slippage=0,corporate_action_mode=True)
        args.update(kw)
        return simulate_portfolio(rows,**args)

    def test_cash_dividend_sold_on_ex_date(self):
        rows=self.install(self.sessions(),self.action(),8)
        rows[1]["close_targets"]={}
        r=self.run_case(rows)
        p=r["path"]
        self.assertEqual(p[2]["holdings"],{})
        self.assertEqual(p[2]["gross_dividend_receivable"],20000)
        self.assertEqual(p[2]["unsettled_sale_proceeds"],80000)
        self.assertEqual(p[2]["available_cash"],900000)
        self.assertEqual(p[-1]["available_cash"],1000000)
        self.assertEqual(p[-1]["gross_dividend_receivable"],0)
        self.assertEqual(r["closed_position_episodes"][0]["gross_dividends"],20000)
        self.assertAlmostEqual(r["closed_position_episodes"][0]["net_return"],0)
        self.assertEqual(r["maximum_close_drawdown"],0)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["dividend_taxes_supported"])

    def test_dividend_not_credited_twice_to_later_episode(self):
        rows=self.install(self.sessions(),self.action(),8)
        rows[1]["close_targets"]={}
        rows[2]["close_targets"]={"2301":0.08}
        rows[3]["close_targets"]={}
        r=self.run_case(rows)
        self.assertEqual(len(r["closed_position_episodes"]),2)
        self.assertEqual([e["gross_dividends"] for e in r["closed_position_episodes"]],
                         [20000,0])
        self.assertAlmostEqual(r["net_marked_return"],0)

    def test_immediate_split_preserves_cost_and_equity(self):
        a=self.action(kind="IMMEDIATE_SHARE_CONVERSION",old_shares=1,
                      new_shares=2,delivery_session="2024-06-05")
        del a["cash_per_share"],a["credit_session"]
        rows=self.install(self.sessions(),a,5)
        rows[2]["close_targets"]={}
        r=self.run_case(rows)
        self.assertEqual(r["path"][2]["holdings"]["2301"],20000)
        self.assertEqual(r["fills"][-1]["shares"],20000)
        self.assertAlmostEqual(r["closed_position_episodes"][0]["net_return"],0)
        self.assertAlmostEqual(r["net_marked_return"],0)

    def test_corporate_action_mode_fails_closed(self):
        base=self.install(self.sessions(),self.action(),8)
        for mutate in (
            lambda x:x[2].pop("corporate_actions"),
            lambda x:x[2].update(corporate_actions=[]),
            lambda x:x[2]["bars"]["2301"].update(corporate_action_clear=True),
            lambda x:x[2]["corporate_actions"][0].update(market="TPEx"),
            lambda x:x[2]["corporate_actions"][0].update(kind="STOCK_DIVIDEND"),
            lambda x:x[0].update(corporate_actions=[self.action()]),
        ):
            rows=deepcopy(base)
            mutate(rows)
            with self.assertRaises(ValueError):
                self.run_case(rows)
        with self.assertRaises(ValueError):
            self.run_case(base,corporate_action_mode=False)


if __name__=="__main__":
    unittest.main()
