"""Synthetic five-model ensemble chronology and grid regression tests."""
import unittest
from datetime import date,timedelta
from src.v3_five_model_ensemble import adaptive_five_blend, MODELS, GRID


class FiveModelEnsembleTests(unittest.TestCase):
    def archives(self):
        start=date(2024,1,2)
        result={}
        for i,kind in enumerate(MODELS):
            predictions,outcomes=[],[]
            protocol=str(i)*64
            for d in range(25):
                day=start+timedelta(days=d)
                for j in range(10):
                    win=j<5
                    p=(.95 if win else .05) if kind=="catboost" else (.1 if win else .9)
                    row=dict(stock_id=str(2300+j),market="TWSE",currently_listed=True,
                             signal_date=day.isoformat(),training_labels_through=(day-timedelta(days=1)).isoformat(),
                             probability=p,protocol_sha256=protocol)
                    predictions.append(row)
                    outcomes.append(dict(row,net_return=.06 if win else -.02,
                                         exit_date=(day+timedelta(days=1)).isoformat(),
                                         label_available_date=(day+timedelta(days=2)).isoformat(),
                                         cohort_available_date=(day+timedelta(days=2)).isoformat()))
            result[kind]=dict(protocol_sha256=protocol,archive_cutoff="2024-02-05",
                               predictions=predictions,mature_outcomes=outcomes)
        return result

    def test_grid_and_past_only_weights(self):
        r=adaptive_five_blend(self.archives())
        self.assertEqual(len(GRID),126)
        self.assertEqual(r["grid_candidates"],126)
        self.assertEqual(len(r["predictions"]),250)
        self.assertEqual(len(r["mature_outcomes"]),250)
        self.assertEqual(r["weight_log"][21]["weights"],dict.fromkeys(MODELS,.2))
        self.assertEqual(r["weight_log"][22]["mature_training_dates"],20)
        self.assertEqual(r["weight_log"][22]["weights"]["catboost"],1.)
        self.assertEqual(r["predictions"][220]["probability"],.95)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["calibrated_probability"])

    def test_future_outcomes_do_not_change_prior_weights(self):
        a=self.archives()
        r=adaptive_five_blend(a)
        for archive in a.values():
            for row in archive["mature_outcomes"]:
                if row["signal_date"]>="2024-01-24":
                    row["net_return"]=-row["net_return"]
        q=adaptive_five_blend(a)
        self.assertEqual(r["predictions"],q["predictions"])
        self.assertEqual(r["weight_log"],q["weight_log"])
        self.assertNotEqual(r["mature_outcomes"],q["mature_outcomes"])

    def test_missing_models_and_partial_cohorts_block(self):
        a=self.archives()
        del a["catboost"]
        with self.assertRaises(ValueError):
            adaptive_five_blend(a)
        a=self.archives()
        for archive in a.values():
            archive["mature_outcomes"].pop()
        with self.assertRaises(ValueError):
            adaptive_five_blend(a)

    def test_mismatched_component_outcomes_block(self):
        a=self.archives()
        a["forest"]["mature_outcomes"][0]["net_return"]=-.5
        with self.assertRaises(ValueError):
            adaptive_five_blend(a)
        a=self.archives()
        a["lightgbm"]["mature_outcomes"][0]["probability"]=.6
        with self.assertRaises(ValueError):
            adaptive_five_blend(a)

    def test_ties_choose_uniform_and_order_invariance(self):
        a=self.archives()
        for archive in a.values():
            for field in ("predictions","mature_outcomes"):
                for row in archive[field]:
                    row["probability"]=.5
        r=adaptive_five_blend(a)
        self.assertTrue(all(w["weights"]==dict.fromkeys(MODELS,.2) for w in r["weight_log"]))
        for archive in a.values():
            archive["predictions"].reverse()
            archive["mature_outcomes"].reverse()
        self.assertEqual(r,adaptive_five_blend(a))


if __name__=="__main__":
    unittest.main()
