import unittest
from datetime import date, timedelta
from unittest.mock import patch
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

    def test_evaluation_window_does_not_trade_before_start_or_after_end(self):
        start=date(2025,1,2)
        rows=[{"trade_date":start+timedelta(days=i),"open":100+i,"low":99+i,
               "high":102+i,"close":101+i,"atr14":1.0} for i in range(6)]
        with patch("src.backtest_engine.signal_score",return_value=(80,0.8,{})):
            summary,trades=simulate_stock(rows,"short",start_date=start+timedelta(days=2),
                                          end_date=start+timedelta(days=4))
        self.assertEqual(summary["data_start"],str(start+timedelta(days=2)))
        self.assertEqual(summary["data_end"],str(start+timedelta(days=4)))
        self.assertTrue(all(t["entry_date"]>=start+timedelta(days=2) for t in trades))
        self.assertTrue(all(t["exit_date"]<=start+timedelta(days=4) for t in trades))

    def test_entry_and_score_exit_execute_next_session_open(self):
        start=date(2025,1,2)
        rows=[]
        for i,(op,lo,cl) in enumerate([(100,99,101),(105,104,106),(108,107,109),(120,119,121)]):
            rows.append({"trade_date":start+timedelta(days=i),"open":op,"low":lo,
                "high":cl+1,"close":cl,"atr14":1.0})
        def fake_signal(row,horizon):
            # Signal at day 1 close enters day 2 open; day 3 close exits day 4 open.
            score={start:80,start+timedelta(days=1):80,
                   start+timedelta(days=2):30,start+timedelta(days=3):30}[row["trade_date"]]
            return score,0.8,{}
        with patch("src.backtest_engine.signal_score",side_effect=fake_signal):
            summary,trades=simulate_stock(rows,"short")
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]["entry_date"],start+timedelta(days=1))
        self.assertEqual(trades[0]["exit_date"],start+timedelta(days=3))
        self.assertAlmostEqual(trades[0]["entry_price"],105*(1+0.001))
        self.assertAlmostEqual(trades[0]["exit_price"],120*(1-0.001))
        self.assertEqual(trades[0]["exit_reason"],"SCORE_EXIT")

if __name__=="__main__": unittest.main()
