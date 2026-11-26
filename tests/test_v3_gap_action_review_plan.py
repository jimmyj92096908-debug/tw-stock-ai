import copy
import unittest
from scripts.v3_gap_action_review_plan import build_review
from scripts.v3_raw_path_overlap_audit import digest

class GapActionReviewTests(unittest.TestCase):
    def inputs(self):
        s=["2024-05-02","2024-05-03","2024-05-06","2024-05-07","2024-05-08","2024-05-09"]
        p=[dict(market="twse",stock_id="2330",signal_date="2024-04-30",
                sessions=s,raw_closes=["100"]*6,approved_total_return=False,
                execution_label_approved=False,corporate_action_coverage_verified=False)]
        g=[dict(market="twse",stock_id="2317",signal_date="2024-04-30",
                reason="MISSING_STOCK_CLOSE",missing_sessions=s[:2]),
           dict(market="twse",stock_id="2330",signal_date="2024-06-28",
                reason="NOT_YET_MATURE",missing_sessions=[])]
        m=dict(scope="V3_FINAL_RAW_PATH_RESEARCH_ONLY",offline_replay_verified=True,model_release="BLOCKED",
               approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
               available_path_rows=1,remaining_rows=2,joined_rows=3,
               raw_paths_sha256=digest(p),remaining_keys_sha256=digest(g),cutoff="2024-07-01",
               available_signal_dates=1,missing_stock_close_rows=1,not_yet_mature_rows=1)
        return dict(summary=m,private_raw_paths=p,private_remaining_keys=g)
    def test_queue_deduplicates_and_excludes_immature(self):
        a=self.inputs()
        before=copy.deepcopy(a)
        r=build_review(a)
        self.assertEqual(r["private_stock_month_queue"],[
            dict(stock_id="2317",month="2024-05",missing_sessions=["2024-05-02","2024-05-03"])])
        self.assertEqual(r["summary"]["action_windows"],1)
        self.assertEqual(r["summary"]["approved_total_return_labels"],0)
        self.assertEqual(r["private_action_windows"][0]["entry_date"],"2024-05-02")
        self.assertEqual(a,before)
    def test_digest_and_out_of_window_rejected(self):
        a=self.inputs()
        a["private_remaining_keys"][0]["missing_sessions"]=["2024-05-10"]
        with self.assertRaises(ValueError):
            build_review(a)
        a["summary"]["remaining_keys_sha256"]=digest(a["private_remaining_keys"])
        with self.assertRaises(ValueError):
            build_review(a)
    def test_excluded_stock_and_label_approval_rejected(self):
        a=self.inputs()
        a["private_remaining_keys"][0]["stock_id"]="1808"
        a["summary"]["remaining_keys_sha256"]=digest(a["private_remaining_keys"])
        with self.assertRaises(ValueError):
            build_review(a)
        a=self.inputs()
        a["private_raw_paths"][0]["approved_total_return"]=True
        a["summary"]["raw_paths_sha256"]=digest(a["private_raw_paths"])
        with self.assertRaises(ValueError):
            build_review(a)
