import copy
import unittest
from src import research_monthly_risk_receipt as risk
from src import research_monthly_ridge_hypothetical as ridge
from tests.test_research_monthly_ridge_hypothetical import fixture

class RiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f,o=fixture()
        cls.result=ridge.evaluate(f,o,label_cutoff="2026-12-31",test_start=f[100]["signal_date"])

    def test_risk_receipt(self):
        r=risk.audit(self.result)
        self.assertEqual(r["window_count"],10)
        self.assertEqual(len(r["scenarios"]),3)
        self.assertFalse(r["annualized_metrics_computed"])
        self.assertFalse(r["continuous_daily_nav_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertTrue(r["positive_mean_excess_all_cost_cases"])

    def test_sampled_drawdown(self):
        r=risk._metrics([.1,-.2,.05])
        self.assertAlmostEqual(r["sampled_window_compounded_return"],-.076)
        self.assertAlmostEqual(r["sampled_window_end_drawdown_fraction"],.2)

    def test_tamper(self):
        for change in (
            lambda r:r["folds"][0]["cost_scenarios"][0].__setitem__("net_excess",9),
            lambda r:r["folds"][0]["cost_scenarios"][2].__setitem__("selected_net",9),
            lambda r:r["folds"].pop(),
            lambda r:r.__setitem__("mean_worst_cost_excess",9),
            lambda r:r.__setitem__("alpha_verified",True),
            lambda r:r["folds"][0].__setitem__("last_mature_training_exit",r["folds"][0]["signal_date"]),
        ):
            r=copy.deepcopy(self.result);change(r)
            with self.assertRaises(ValueError):risk.audit(r)

    def test_insufficient(self):
        f,o=fixture(17)
        r=ridge.evaluate(f,o,label_cutoff="2026-12-31",test_start=f[50]["signal_date"])
        self.assertEqual(risk.audit(r)["status"],"INSUFFICIENT_HYPOTHETICAL_WINDOWS")
