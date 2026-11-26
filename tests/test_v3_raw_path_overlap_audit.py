import copy
import unittest
from scripts.v3_raw_path_overlap_audit import audit_overlap,digest


class RawPathOverlapTests(unittest.TestCase):
    def inputs(self):
        names=["f"+str(i) for i in range(12)]+[
            "institutional_net_shares_20","institutional_turnover_shares_20","institutional_imbalance_20"]
        row=dict(market="TWSE",stock_id="2330",signal_date="2024-04-30",
                 features=dict(zip(names,[.1]*12+[20,100,.2])),
                 historical_reconstruction_only=True,strict_point_in_time_verified=False,
                 approved_training_feature=False)
        joined=dict(summary=dict(status="RETROSPECTIVE_JOIN_RESEARCH_ONLY",
                  model_release="BLOCKED",approved_training_feature_rows=0,matched_rows=1,
                  matched_rows_sha256=digest([row]),feature_names=names),
                  retrospective_joined_factors=[row])
        path=dict(market="twse",stock_id="2330",signal_date="2024-04-30",
                  feature_vector=[.1]*12,approved_total_return=False,
                  corporate_action_coverage_verified=False,
                  sessions=["2024-05-02","2024-05-03","2024-05-06","2024-05-07","2024-05-08","2024-05-09"],
                  raw_closes=[100,101,102,103,104,105])
        actions=dict(summary=dict(model_release="BLOCKED",approved_total_return_labels=0,
                     corporate_action_coverage_verified=False,matched_raw_feature_label_rows=1,
                     matched_panel_sha256=digest([path])),private_matched_rows=[path])
        return joined,actions

    def test_exact_overlap_does_not_approve_labels(self):
        j,a=self.inputs()
        r=audit_overlap(j,a)
        self.assertEqual(r["exact_key_overlap_rows"],1)
        self.assertEqual(r["matching_technical_vectors"],1)
        self.assertEqual(r["strictly_post_signal_ordered_paths"],1)
        self.assertTrue(r["action_canonical_digest_matches"])
        self.assertEqual(r["approved_total_return_labels"],0)
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_no_cross_market_match(self):
        j,a=self.inputs()
        a["private_matched_rows"][0]["market"]="tpex"
        r=audit_overlap(j,a)
        self.assertEqual(r["exact_key_overlap_rows"],0)
        self.assertEqual(r["no_raw_path_rows"],1)

    def test_mismatched_vector_and_session_are_not_hidden(self):
        j,a=self.inputs()
        p=a["private_matched_rows"][0]
        p["feature_vector"][0]=.2
        p["sessions"][0]="2024-04-30"
        r=audit_overlap(j,a)
        self.assertEqual(r["exact_key_overlap_rows"],1)
        self.assertEqual(r["matching_technical_vectors"],0)
        self.assertEqual(r["strictly_post_signal_ordered_paths"],0)
        self.assertFalse(r["action_canonical_digest_matches"])

    def test_tampering_or_approval_rejected(self):
        j,a=self.inputs()
        j["retrospective_joined_factors"][0]["features"]["f0"]=.2
        with self.assertRaises(ValueError):
            audit_overlap(j,a)
        j,a=self.inputs()
        a["private_matched_rows"][0]["approved_total_return"]=True
        with self.assertRaises(ValueError):
            audit_overlap(j,a)
