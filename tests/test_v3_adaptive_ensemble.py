"""Synthetic tests for past-only adaptive ensemble weights."""
import unittest
from datetime import date,timedelta
from src.v3_adaptive_ensemble import adaptive_blend_archives


class AdaptiveEnsembleTests(unittest.TestCase):
    def archives(self):
        start=date(2024,1,2)
        result=[]
        for protocol,good in (("a"*64,True),("b"*64,False)):
            predictions,outcomes=[],[]
            for i in range(25):
                day=start+timedelta(days=i)
                for j in range(10):
                    win=j<5
                    p=.9 if win==good else .1
                    row=dict(stock_id=str(2300+j),market="TWSE",currently_listed=True,
                             signal_date=day.isoformat(),training_labels_through=(day-timedelta(days=1)).isoformat(),
                             probability=p,protocol_sha256=protocol)
                    predictions.append(row)
                    outcomes.append(dict(row,net_return=.06 if win else -.02,
                                         exit_date=(day+timedelta(days=1)).isoformat(),
                                         label_available_date=(day+timedelta(days=2)).isoformat(),
                                         cohort_available_date=(day+timedelta(days=2)).isoformat()))
            result.append(dict(protocol_sha256=protocol,archive_cutoff="2024-02-05",
                               predictions=predictions,mature_outcomes=outcomes))
        return result

    def test_fallback_then_past_only_selection(self):
        a,b=self.archives()
        r=adaptive_blend_archives(a,b)
        self.assertEqual(len(r["predictions"]),250)
        self.assertEqual(len(r["mature_outcomes"]),250)
        self.assertEqual(r["weight_log"][21]["logistic_weight"],.5)
        self.assertEqual(r["weight_log"][21]["mature_training_dates"],19)
        self.assertEqual(r["weight_log"][22]["logistic_weight"],1.)
        self.assertEqual(r["weight_log"][22]["mature_training_rows"],200)
        self.assertEqual(r["predictions"][220]["probability"],.9)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["calibrated_probability"])

    def test_future_outcomes_cannot_change_earlier_weights(self):
        a,b=self.archives()
        r=adaptive_blend_archives(a,b)
        for archive in (a,b):
            for row in archive["mature_outcomes"]:
                if row["signal_date"]>="2024-01-24":
                    row["net_return"]=-row["net_return"]
        q=adaptive_blend_archives(a,b)
        self.assertEqual(r["weight_log"],q["weight_log"])
        self.assertEqual(r["predictions"],q["predictions"])
        self.assertNotEqual(r["mature_outcomes"],q["mature_outcomes"])

    def test_partial_cohort_and_mismatched_outcomes_rejected(self):
        a,b=self.archives()
        a["mature_outcomes"].pop()
        b["mature_outcomes"].pop()
        with self.assertRaises(ValueError):
            adaptive_blend_archives(a,b)
        a,b=self.archives()
        b["mature_outcomes"][0]["net_return"]=-.5
        with self.assertRaises(ValueError):
            adaptive_blend_archives(a,b)

    def test_unavailable_outcomes_keep_fallback(self):
        a,b=self.archives()
        for archive in (a,b):
            archive["mature_outcomes"]=[]
        r=adaptive_blend_archives(a,b)
        self.assertTrue(all(w["logistic_weight"]==.5 for w in r["weight_log"]))
        self.assertEqual(r["mature_outcomes"],[])

    def test_deterministic_order(self):
        a,b=self.archives()
        r=adaptive_blend_archives(a,b)
        for archive in (a,b):
            archive["predictions"].reverse()
            archive["mature_outcomes"].reverse()
        self.assertEqual(r,adaptive_blend_archives(a,b))


    def test_selector_cutoff_reflects_latest_used_label(self):
        a=self.archives()
        for archive in a:
            for field in ("predictions","mature_outcomes"):
                for row in archive[field]:
                    row["training_labels_through"]="2024-01-01"
        r=adaptive_blend_archives(*a)
        self.assertEqual(r["predictions"][210]["training_labels_through"],"2024-01-01")
        self.assertEqual(r["predictions"][220]["training_labels_through"],"2024-01-23")
        self.assertEqual(r["mature_outcomes"][220]["training_labels_through"],"2024-01-23")
        self.assertEqual(r["weight_log"][22]["latest_cohort_available"],"2024-01-23")


if __name__=="__main__":
    unittest.main()
