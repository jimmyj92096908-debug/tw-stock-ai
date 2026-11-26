"""Regime-conditioned ensemble fallback and chronological isolation tests."""
import unittest
from datetime import date,timedelta
from src.v3_five_model_ensemble import adaptive_five_blend,MODELS
from src.v3_purged_logistic_baseline import _hash
from tests import test_v3_five_model_ensemble as fixtures


class RegimeEnsembleTests(unittest.TestCase):
    def archives(self):
        return fixtures.FiveModelEnsembleTests().archives()

    def states(self):
        start=date(2024,1,2)
        rows=[]
        for i in range(25):
            d=(start+timedelta(days=i)).isoformat()
            rows.append(dict(signal_date=d,regime="UPTREND" if i<23 else
                             "DOWNTREND" if i==23 else "UNKNOWN_HISTORY",
                             volatile_heuristic=False,last_available_close=d))
        return dict(index_id="TWSE_TAIEX",states=rows,states_sha256=_hash(rows))

    def test_same_regime_global_and_unknown_fallback(self):
        a=self.archives()
        result=adaptive_five_blend(a,regimes=self.states())
        log=result["weight_log"]
        self.assertEqual(log[21]["status"],"UNIFORM_FALLBACK")
        self.assertEqual(log[22]["status"],"REGIME_MATCHED_SELECTION")
        self.assertEqual(log[22]["mature_training_dates"],20)
        self.assertEqual(log[22]["weights"]["catboost"],1.)
        self.assertEqual(log[23]["status"],"GLOBAL_FALLBACK_SELECTION")
        self.assertEqual(log[24]["weights"],dict.fromkeys(MODELS,.2))
        self.assertTrue(log[24]["new_exposure_blocked_by_regime"])
        self.assertNotEqual(result["protocol_sha256"],adaptive_five_blend(a)["protocol_sha256"])
        self.assertEqual(result["model_release"],"BLOCKED")

    def test_future_regime_and_labels_do_not_change_prior_forecasts(self):
        a=self.archives()
        states=self.states()
        r=adaptive_five_blend(a,regimes=states)
        states["states"][-1]["regime"]="UPTREND"
        states["states_sha256"]=_hash(states["states"])
        for archive in a.values():
            for row in archive["mature_outcomes"]:
                if row["signal_date"]>="2024-01-24":
                    row["net_return"]=-row["net_return"]
        q=adaptive_five_blend(a,regimes=states)
        self.assertEqual(r["predictions"][:240],q["predictions"][:240])
        self.assertEqual(r["weight_log"][:24],q["weight_log"][:24])

    def test_missing_tampered_or_stale_regime_rejected(self):
        a=self.archives()
        states=self.states()
        states["states"].pop()
        with self.assertRaises(ValueError):
            adaptive_five_blend(a,regimes=states)
        states["states_sha256"]=_hash(states["states"])
        with self.assertRaises(ValueError):
            adaptive_five_blend(a,regimes=states)
        states=self.states()
        states["states"][0]["last_available_close"]="2024-01-01"
        states["states_sha256"]=_hash(states["states"])
        with self.assertRaises(ValueError):
            adaptive_five_blend(a,regimes=states)


if __name__=="__main__":
    unittest.main()
