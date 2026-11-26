"""Execution-label cohort uses shared portfolio accounting, not synthetic returns."""
import unittest
from src.v3_execution_label_cohort import execution_label_cohort


class ExecutionLabelCohortTests(unittest.TestCase):
    def args(self):
        def bar(op,hi,lo,close):
            return dict(market="TWSE",currently_listed=True,corporate_action_clear=True,
                        open=op,high=hi,low=lo,close=close,buy_eligible=True,sell_eligible=True,
                        buy_capacity_shares=100000,sell_capacity_shares=100000)
        sessions=[
            dict(date="2024-05-01",bars={"2330":bar(100,100,100,100),"2401":bar(100,100,100,100)}),
            dict(date="2024-05-02",bars={"2330":bar(100,112,99,111),"2401":bar(100,101,93,95)}),
            dict(date="2024-05-03",bars={"2330":bar(111,111,111,111),"2401":bar(95,95,95,95)})]
        candidates=[dict(stock_id=s,market="TWSE",currently_listed=True,signal_date="2024-05-01",
                         feature_available_date="2024-05-01",feature_vintage_declared=True,
                         features={"score":.5}) for s in ("2330","2401")]
        return dict(candidates=candidates,sessions=sessions,label_available_date="2024-05-03",
                    horizon_sessions=2,commission=0,sell_tax=0,slippage=0)

    def test_closed_cohort_exact_stop_profit_and_delayed_availability(self):
        r=execution_label_cohort(**self.args())
        self.assertEqual(r["status"],"COMPLETE_SUPPLIED_COHORT")
        self.assertEqual(len(r["training_rows"]),2)
        self.assertAlmostEqual(r["training_rows"][0]["net_return"],.1)
        self.assertAlmostEqual(r["training_rows"][1]["net_return"],-.05)
        self.assertTrue(all(x["exit_date"]=="2024-05-02" and x["label_available_date"]=="2024-05-03"
                            for x in r["training_rows"]))
        self.assertFalse(r["whole_portfolio_execution_parity_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_incomplete_exit_and_no_entry_block_entire_cohort(self):
        for mode in ("unresolved","no_entry"):
            a=self.args()
            if mode=="unresolved":
                for s in a["sessions"][1:]:
                    s["bars"]["2401"].update(open=100,high=100,low=100,close=100)
            else:
                a["sessions"][1]["bars"]["2401"]["buy_eligible"]=False
            r=execution_label_cohort(**a)
            self.assertEqual(r["status"],"INCOMPLETE_COHORT_BLOCKED")
            self.assertEqual(r["closed_candidate_count"],1)
            self.assertEqual(r["training_rows"],[])

    def test_costs_and_protocol_change(self):
        a=self.args()
        r=execution_label_cohort(**a)
        a.update(commission=.001425,sell_tax=.003,slippage=.001)
        q=execution_label_cohort(**a)
        self.assertEqual(len(q["training_rows"]),2)
        self.assertLess(q["training_rows"][0]["net_return"],r["training_rows"][0]["net_return"])
        self.assertNotEqual(r["label_protocol_sha256"],q["label_protocol_sha256"])

    def test_stop_first_and_pending_exit(self):
        a=self.args()
        a["sessions"][1]["bars"]["2330"].update(low=90,sell_eligible=False)
        a["sessions"][2]["bars"]["2330"].update(open=90,high=91,low=89,close=90)
        r=execution_label_cohort(**a)
        self.assertAlmostEqual(r["training_rows"][0]["net_return"],-.1)
        self.assertEqual(r["training_rows"][0]["exit_date"],"2024-05-03")

    def test_invalid_availability_and_outcome_fields(self):
        a=self.args()
        a["label_available_date"]="2024-05-02"
        with self.assertRaises(ValueError):
            execution_label_cohort(**a)
        a=self.args()
        a["candidates"][0]["net_return"]=1
        with self.assertRaises(ValueError):
            execution_label_cohort(**a)


if __name__=="__main__":
    unittest.main()
