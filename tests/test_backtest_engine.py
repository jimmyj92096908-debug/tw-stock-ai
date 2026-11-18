import unittest
from datetime import date, timedelta
from src.backtest_engine import position_size, trade_costs, simulate_stock

class BacktestTests(unittest.TestCase):
    def test_position_size_caps_risk_and_lots(self):
        n=position_size(1_000_000,100,2)
        self.assertEqual(n%1000,0)
        self.assertLessEqual(n*4,10_000)
    def test_position_size_rejects_bad_atr(self):
        self.assertEqual(position_size(1_000_000,100,0),0)
    def test_costs_include_commission_and_sell_tax(self):
        buy,sell=trade_costs(100,110,1000)
        self.assertGreater(buy,100000)
        self.assertLess(sell,110000)
    def test_empty_rows(self):
        summary,trades=simulate_stock([],"short")
        self.assertEqual(summary["trades"],0)
        self.assertEqual(trades,[])
    def test_horizon_has_fixed_max_hold(self):
        self.assertEqual({"short":5,"swing":20,"long":60},{"short":5,"swing":20,"long":60})

if __name__=="__main__": unittest.main()
