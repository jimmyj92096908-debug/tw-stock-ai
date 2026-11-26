"""Synthetic exit stress scenarios, not executable price evidence."""
import unittest

from src.v3_exit_stress_research import replay_exit


class ExitStressTests(unittest.TestCase):
    def bar(self, day, op=100, hi=102, lo=98, close=100, **overrides):
        row = dict(date=day, open=op, high=hi, low=lo, close=close,
                   corporate_action_clear=True, sell_eligible=True,
                   sell_capacity_shares=2000)
        row.update(overrides)
        return row

    def replay(self, rows, **overrides):
        args = dict(entry_date="2024-01-01", entry_price=100, shares=2000,
                    commission=0, sell_tax=0, slippage=0)
        args.update(overrides)
        return replay_exit(sessions=rows, **args)

    def test_gap_stop_is_not_stop_price(self):
        r = self.replay([self.bar("2024-01-02",80,85,78,82)])
        self.assertEqual(r["fills"][0]["reason"],"GAP_STOP")
        self.assertEqual(r["fills"][0]["fill"],80)
        self.assertAlmostEqual(r["net_closed_return"],-0.2)
        self.assertFalse(r["trading_approved"])

    def test_dual_touch_uses_stop_first(self):
        r = self.replay([self.bar("2024-01-02",100,112,94,108)])
        self.assertEqual(r["fills"][0]["reason"],"STOP_FIRST")
        self.assertEqual(r["fills"][0]["fill"],95)

    def test_trailing_only_uses_previous_session_high(self):
        r = self.replay([self.bar("2024-01-02",100,108,98,107),
                         self.bar("2024-01-03",106,107,101,103)])
        self.assertEqual(r["fills"][0]["date"],"2024-01-03")
        self.assertAlmostEqual(r["fills"][0]["fill"],102.6)
        self.assertAlmostEqual(r["net_closed_return"],0.026)

    def test_blocked_and_partial_exit_persists(self):
        rows = [self.bar("2024-01-02",90,90,90,90,sell_eligible=False),
                self.bar("2024-01-03",80,82,79,81,sell_capacity_shares=None),
                self.bar("2024-01-04",75,77,74,76,sell_capacity_shares=1500),
                self.bar("2024-01-05",70,73,69,72,sell_capacity_shares=1000)]
        partial = self.replay(rows[:3])
        self.assertEqual(partial["remaining_shares"],1000)
        self.assertTrue(partial["exit_pending"])
        self.assertIsNone(partial["net_closed_return"])
        r = self.replay(rows)
        self.assertEqual([e["filled_shares"] for e in r["events"]],[0,0,1000,1000])
        self.assertEqual([f["reason"] for f in r["fills"]],["PENDING_EXIT"]*2)
        self.assertAlmostEqual(r["net_closed_return"],-0.275)
        self.assertFalse(r["exit_pending"])

    def test_profit_and_costs(self):
        r = self.replay([self.bar("2024-01-02",105,112,104,111)],
                        commission=0.001425,sell_tax=0.003,slippage=0.001)
        fill=100*1.10*0.999
        self.assertAlmostEqual(r["fills"][0]["fill"],fill)
        self.assertAlmostEqual(r["net_closed_return"],
                               fill*(1-0.001425-0.003)/(100*1.001425)-1)

    def test_bad_inputs(self):
        for row in (self.bar("2024-01-01"),
                    self.bar("2024-01-02",hi=90),
                    self.bar("2024-01-02",sell_eligible=1),
                    self.bar("2024-01-02",sell_capacity_shares=-1),
                    self.bar("2024-01-02",corporate_action_clear=False)):
            with self.assertRaises(ValueError):
                self.replay([row])


if __name__=="__main__":
    unittest.main()
