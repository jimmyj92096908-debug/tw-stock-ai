"""Synthetic portfolio ledger checks; no claims of executable fills."""
import unittest
from copy import deepcopy
from datetime import date,timedelta

from src.v3_portfolio_accounting import simulate_portfolio


class PortfolioAccountingTests(unittest.TestCase):
    def sessions(self, targets, prices=None):
        start=date(2024,1,2)
        rows=[]
        for i,target in enumerate(targets):
            p=prices[i] if prices else 10
            rows.append({"date":(start+timedelta(days=i)).isoformat(),
                         "bars":{s:{"market":"TWSE","currently_listed":True,
                                    "corporate_action_clear":True,"open":p,"close":p}
                                 for s in ("2301","2302")},
                         "close_targets":target})
        return rows

    def run_case(self, rows, **kwargs):
        return simulate_portfolio(rows, **kwargs)

    def test_next_open_and_costs(self):
        r=self.run_case(self.sessions([{"2301":0.1},{},None,None,None],
                                      [10,10,12,12,12]))
        self.assertEqual(len(r["fills"]),2)
        buy,sell=r["fills"]
        self.assertEqual(buy["date"],"2024-01-03")
        self.assertEqual(sell["date"],"2024-01-04")
        self.assertEqual(buy["shares"],9000)
        expected_buy=9000*10*1.001*1.001425
        expected_sell=9000*12*0.999*(1-0.001425-0.003)
        self.assertAlmostEqual(buy["cash_flow"],-expected_buy)
        self.assertAlmostEqual(sell["cash_flow"],expected_sell)
        self.assertAlmostEqual(r["closed_position_episodes"][0]["net_pnl"],
                               expected_sell-expected_buy)
        self.assertAlmostEqual(r["path"][2]["unsettled_sale_proceeds"],expected_sell)
        self.assertAlmostEqual(r["path"][3]["unsettled_sale_proceeds"],expected_sell)
        self.assertEqual(r["path"][4]["unsettled_sale_proceeds"],0)
        self.assertAlmostEqual(r["path"][4]["equity"],1000000-expected_buy+expected_sell)
        self.assertEqual(r["closed_episode_win_rate"],1)

    def test_partial_exit_episode_and_terminal_signal(self):
        r=self.run_case(self.sessions([{"2301":0.1},{"2301":0.05},{},None,
                                       {"2302":0.1}]),
                        commission=0,sell_tax=0,slippage=0)
        self.assertEqual([f["shares"] for f in r["fills"]],[10000,5000,5000])
        self.assertEqual(len(r["closed_position_episodes"]),1)
        self.assertAlmostEqual(r["closed_position_episodes"][0]["net_pnl"],0)
        self.assertEqual(r["closed_episode_win_rate"],0)
        self.assertTrue(r["terminal_target_unexecuted"])

    def test_marked_loss_and_open_episode(self):
        r=self.run_case(self.sessions([{"2301":0.1},None,None],[10,10,5]),
                        commission=0,sell_tax=0,slippage=0)
        self.assertEqual(r["open_position_count"],1)
        self.assertIsNone(r["closed_episode_win_rate"])
        self.assertAlmostEqual(r["maximum_close_drawdown"],0.05)
        self.assertAlmostEqual(r["net_marked_return"],-0.05)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["stop_execution_supported"])

    def test_cash_and_accounting_conservation(self):
        r=self.run_case(self.sessions([{"2301":0.1,"2302":0.1},
                                       {"2301":0.05,"2302":0.1},
                                       {"2302":0.1},None,None]))
        for p in r["path"]:
            self.assertGreaterEqual(p["available_cash"],0)
            self.assertAlmostEqual(p["equity"],p["available_cash"]+
                                   p["unsettled_sale_proceeds"]+p["market_value"])
            self.assertTrue(all(q%1000==0 for q in p["holdings"].values()))

    def test_bad_inputs_fail_closed(self):
        base=self.sessions([{"2301":0.1},None])
        for mutate in (
            lambda r:r[0].update(close_targets={"2301":0.11}),
            lambda r:r[0].update(close_targets={"9999":0.1}),
            lambda r:r[1]["bars"].pop("2302"),
            lambda r:r[1]["bars"]["2301"].update(corporate_action_clear=False),
            lambda r:r[1]["bars"]["2301"].update(currently_listed=False),
            lambda r:r[1]["bars"]["2301"].update(open=float("nan")),
            lambda r:r[1].update(date=r[0]["date"]),
        ):
            rows=deepcopy(base)
            mutate(rows)
            with self.assertRaises(ValueError):
                self.run_case(rows)


if __name__=="__main__":
    unittest.main()
