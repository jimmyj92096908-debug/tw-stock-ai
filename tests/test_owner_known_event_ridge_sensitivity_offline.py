from datetime import date
import unittest
from scripts import owner_known_event_ridge_sensitivity_offline as m
from tests.test_owner_raw_price_ridge_diagnostic_offline import RawDiagnosticTests

class KnownEventRidgeTests(unittest.TestCase):
    def fixture(self):
        ids,features,late=RawDiagnosticTests().fixture()
        base,paths=m.raw.evaluate(ids,features,late)
        self.assertGreaterEqual(len(base["folds"]),10)
        return ids,features,late,base,paths

    def test_identity_and_blocked_release(self):
        ids,features,late,base,paths=self.fixture()
        result,_,_=m.compare(ids,features,late,{"events":[],"in_holding_events":0})
        self.assertEqual(result["selection_changed_windows"],0)
        self.assertEqual(result["approved_total_return_labels"],0)
        self.assertEqual(result["model_release"],"BLOCKED")
        self.assertTrue(result["unknown_event_paths_not_certified"])
        for f in result["folds"]:
            self.assertEqual(f["raw_fit_sha256"],f["known_event_fit_sha256"])
            for c in f["cost_scenarios"]:
                self.assertAlmostEqual(c["raw_fit_raw_eval_excess"],c["known_event_fit_eval_excess"])

    def test_event_only_affects_future_training(self):
        ids,features,late,base,paths=self.fixture()
        target=base["folds"][0]["signal_date"]
        p=next(p for p in paths if p["signal_date"]==target)
        e={"signal_date":target,"stock_id":p["stock_id"],"event_date":p["sessions"][1],
           "entry_close_excluded":False,"cash_per_old_share_candidate":"1","share_multiplier_candidate":"1.1"}
        result,_,_=m.compare(ids,features,late,{"events":[e],"in_holding_events":1})
        first=result["folds"][0]
        self.assertEqual(first["known_event_training_rows"],0)
        self.assertEqual(first["raw_fit_sha256"],first["known_event_fit_sha256"])
        self.assertNotEqual(first["cost_scenarios"][0]["raw_fit_raw_eval_excess"],
                            first["cost_scenarios"][0]["raw_fit_known_event_eval_excess"])
        self.assertTrue(all(f["known_event_training_rows"]==1 for f in result["folds"][1:]))
        self.assertTrue(all(f["last_mature_training_exit"]<f["signal_date"] for f in result["folds"]))
        with self.assertRaises(ValueError):
            m.compare(ids,features,late,{"events":[e,e],"in_holding_events":2})

    def test_entry_close_exclusion(self):
        ids,features,late,base,paths=self.fixture()
        p=paths[0]
        e={"signal_date":p["signal_date"],"stock_id":p["stock_id"],"event_date":p["sessions"][0],
           "entry_close_excluded":True,"cash_per_old_share_candidate":"1","share_multiplier_candidate":"1"}
        result,_,_=m.compare(ids,features,late,{"events":[e],"in_holding_events":0})
        self.assertEqual(result["known_event_corrected_paths"],0)
        self.assertEqual(result["selection_changed_windows"],0)
        e["entry_close_excluded"]=False
        with self.assertRaises(ValueError):
            m.compare(ids,features,late,{"events":[e],"in_holding_events":1})
