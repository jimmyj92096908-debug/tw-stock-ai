import copy
from datetime import date
import unittest

from scripts.v3_raw_path_overlap_audit import expansion_plan,digest
from scripts.v3_raw_path_recovery import recover
from scripts.v3_final_raw_path_audit import reconcile

class FinalRawPathTests(unittest.TestCase):
    def inputs(self):
        names=["f"+str(i) for i in range(12)]+[
            "institutional_net_shares_20","institutional_turnover_shares_20","institutional_imbalance_20"]
        rows=[dict(market="twse",stock_id=s,signal_date=d,features=dict(zip(names,[.1]*12+[20,100,.2])),
                   historical_reconstruction_only=True,strict_point_in_time_verified=False,
                   approved_training_feature=False)
              for s,d in [("2330","2024-04-30"),("2317","2024-04-30"),("2303","2024-04-30"),("2317","2024-06-28")]]
        j=dict(summary=dict(status="RETROSPECTIVE_JOIN_RESEARCH_ONLY",model_release="BLOCKED",
                approved_training_feature_rows=0,matched_rows=len(rows),matched_rows_sha256=digest(rows),feature_names=names),
                retrospective_joined_factors=rows)
        paths=[dict(market="twse",stock_id="2330",signal_date="2024-04-30",feature_vector=[.1]*12,
                    sessions=["2024-05-02","2024-05-03","2024-05-06","2024-05-07","2024-05-08","2024-05-09"],
                    raw_closes=["100"]*6,raw_gross_return="0",approved_total_return=False,corporate_action_coverage_verified=False)]
        a=dict(summary=dict(model_release="BLOCKED",approved_total_return_labels=0,corporate_action_coverage_verified=False,
                            matched_raw_feature_label_rows=1,matched_panel_sha256=digest(paths)),private_matched_rows=paths)
        p=expansion_plan(j,a)
        def lookup(d):
            return {"2330":"100","2317":"50"}
        s=recover(p,a,lookup,date(2024,7,1))
        return j,a,p,s,lookup
    def test_replay_and_gap_reconciliation(self):
        args=self.inputs()
        before=copy.deepcopy(args[:4])
        r=reconcile(*args)
        m=r["summary"]
        self.assertEqual(m["available_path_rows"],2)
        self.assertEqual(m["missing_stock_close_rows"],1)
        self.assertEqual(m["not_yet_mature_rows"],1)
        self.assertEqual(m["original_technical_vector_parity_rows"],1)
        self.assertEqual(m["execution_labels_approved"],0)
        self.assertFalse(m["recovered_vectors_independently_verified"])
        self.assertEqual(len(r["private_remaining_keys"][0]["missing_sessions"]),6)
        self.assertEqual(args[:4],before)
        self.assertTrue(all("features" not in row for row in r["private_raw_paths"]))
    def test_reject_recovery_tampering(self):
        j,a,p,s,lookup=self.inputs()
        s["private_recovered_paths"][0]["raw_closes"][0]="51"
        with self.assertRaises(ValueError):
            reconcile(j,a,p,s,lookup)
    def test_reject_plan_tampering(self):
        j,a,p,s,lookup=self.inputs()
        p["private_missing_keys"][0]["stock_id"]="1589"
        with self.assertRaises(ValueError):
            reconcile(j,a,p,s,lookup)
