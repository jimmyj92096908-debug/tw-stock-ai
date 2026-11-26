"""Ledger performance acceptance regression tests."""
import unittest
from datetime import date,timedelta
from src.v3_portfolio_performance_acceptance import portfolio_performance_acceptance


class PortfolioPerformanceTests(unittest.TestCase):
    def ledger(self):
        start=date(2024,1,1)
        path=[]
        equity=1000000.
        for i in range(102):
            if i:
                equity*=1.004 if i%2 else .999
            path.append(dict(date=(start+timedelta(days=i)).isoformat(),
                             equity=equity,available_cash=equity,unsettled_sale_proceeds=0.,
                             market_value=0.,gross_dividend_receivable=0.,holdings={}))
        episodes=[dict(stock_id=str(2300+j),entry_date=path[i]["date"],
                       exit_date=path[i+1]["date"],net_return=.06 if j<4 else -.02,
                       net_pnl=600 if j<4 else -200)
                  for i in range(1,101) for j in range(5)]
        return dict(path=path,closed_position_episodes=episodes,open_position_count=0,
                    maximum_close_drawdown=.001,net_marked_return=equity/path[0]["equity"]-1)

    def test_metrics_numeric_pass_is_not_release(self):
        r=portfolio_performance_acceptance(self.ledger())
        self.assertEqual(r["metrics"]["closed_trade_count"],500)
        self.assertAlmostEqual(r["metrics"]["net_win_rate"],.8)
        self.assertAlmostEqual(r["metrics"]["mean_return_payoff_ratio"],3)
        self.assertAlmostEqual(r["metrics"]["money_profit_factor"],12)
        self.assertAlmostEqual(r["metrics"]["sensitivity_lower_estimate"],.8)
        self.assertTrue(r["all_numeric_gates_met"])
        self.assertFalse(r["trading_approved"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_empty_trades_and_zero_volatility_do_not_pass(self):
        a=self.ledger()
        a["closed_position_episodes"]=[]
        for row in a["path"]:
            row.update(equity=1000000.,available_cash=1000000.)
        a.update(maximum_close_drawdown=0.,net_marked_return=0.)
        r=portfolio_performance_acceptance(a)
        self.assertIsNone(r["metrics"]["illustrative_annualized_sharpe"])
        self.assertIsNone(r["metrics"]["net_win_rate"])
        self.assertFalse(r["all_numeric_gates_met"])

    def test_actual_money_profit_factor_not_return_ratio(self):
        a=self.ledger()
        for r in a["closed_position_episodes"]:
            if r["net_pnl"]<0:
                r["net_pnl"]=-2000
        q=portfolio_performance_acceptance(a)
        self.assertAlmostEqual(q["metrics"]["money_profit_factor"],1.2)
        self.assertFalse(q["research_gates"]["money_profit_factor_2"])

    def test_inconsistent_ledger_rejected(self):
        a=self.ledger()
        a["path"][1]["available_cash"]-=10
        with self.assertRaises(ValueError):
            portfolio_performance_acceptance(a)
        a=self.ledger()
        a["closed_position_episodes"].append(a["closed_position_episodes"][0].copy())
        with self.assertRaises(ValueError):
            portfolio_performance_acceptance(a)

    def test_open_positions_block_numeric_acceptance(self):
        a=self.ledger()
        a["path"][-1]["holdings"]={"2401":1000}
        a["open_position_count"]=1
        r=portfolio_performance_acceptance(a)
        self.assertFalse(r["research_gates"]["no_open_episodes"])
        self.assertFalse(r["all_numeric_gates_met"])


if __name__=="__main__":
    unittest.main()
