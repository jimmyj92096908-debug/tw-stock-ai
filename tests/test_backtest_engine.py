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


    def test_cagr_uses_evaluation_window_not_indicator_warmup(self):
        rows=[
            {"trade_date":date(2021,1,4),"open":80,"low":79,"high":82,"close":81,"atr14":1.0},
            {"trade_date":date(2025,1,2),"open":100,"low":99,"high":102,"close":101,"atr14":1.0},
            {"trade_date":date(2026,1,2),"open":105,"low":104,"high":107,"close":106,"atr14":1.0},
            {"trade_date":date(2026,1,5),"open":110,"low":109,"high":112,"close":111,"atr14":1.0},
        ]
        scores={date(2021,1,4):30,date(2025,1,2):80,
                date(2026,1,2):30,date(2026,1,5):30}
        with patch("src.backtest_engine.signal_score",
                   side_effect=lambda row,horizon:(scores[row["trade_date"]],0.8,{})):
            summary,trades=simulate_stock(rows,"short",start_date=date(2025,1,2),
                                          end_date=date(2026,1,5))
        self.assertEqual(summary["evaluation_days"],368)
        years=368/365.25
        expected=((summary["ending_equity"]/1_000_000)**(1/years)-1)*100
        self.assertAlmostEqual(summary["cagr_pct"],expected,places=8)
        self.assertEqual(len(trades),1)

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
