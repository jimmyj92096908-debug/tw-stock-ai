import json
import unittest
from scripts.v3_twse_action_candidate_scan import parse,parse_response,scan
from scripts.v3_gap_action_review_plan import build_review
from scripts.v3_raw_path_overlap_audit import digest

class ActionCandidateScanTests(unittest.TestCase):
    def inputs(self):
        s=["2024-05-02","2024-05-03","2024-05-06","2024-05-07","2024-05-08","2024-05-09"]
        p=[dict(market="twse",stock_id="2330",signal_date="2024-04-30",
                sessions=s,raw_closes=["100"]*6,approved_total_return=False,
                execution_label_approved=False,corporate_action_coverage_verified=False)]
        g=[]
        m=dict(scope="V3_FINAL_RAW_PATH_RESEARCH_ONLY",offline_replay_verified=True,model_release="BLOCKED",
               approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
               available_path_rows=1,remaining_rows=0,joined_rows=1,
               raw_paths_sha256=digest(p),remaining_keys_sha256=digest(g),cutoff="2024-07-01",
               available_signal_dates=1,missing_stock_close_rows=0,not_yet_mature_rows=0)
        a=dict(summary=m,private_raw_paths=p,private_remaining_keys=g)
        return a,build_review(a)
    def rows(self):
        return parse(json.dumps({"stat":"OK","fields":["股票代號","除權息日期","權/息"],
            "data":[["2330","113/05/02","息"],["2330","113/05/03","息"],
                    ["2330","113/05/04","息"],["2330","113/04/30","息"],
                    ["2317","113/05/03","權"]]}).encode(),"ex")
    def test_entry_holding_and_non_session_distinguished(self):
        a,p=self.inputs()
        r=scan(a,p,lambda kind,start,end:(self.rows() if kind=="ex" else [],"a"*64,"CANDIDATE_SCAN_ONLY"))
        m=r["summary"]
        self.assertEqual(m["windows_with_both_candidate_scans"],1)
        self.assertEqual(m["candidate_event_rows"],3)
        self.assertEqual(m["entry_day_candidate_paths"],1)
        self.assertEqual(m["in_holding_affected_paths"],1)
        self.assertEqual(m["outside_saved_session_candidate_paths"],1)
        self.assertFalse(m["corporate_action_coverage_verified"])
        self.assertEqual(m["approved_total_return_labels"],0)
    def test_pending_source_not_complete(self):
        a,p=self.inputs()
        r=scan(a,p,lambda kind,start,end:None)
        self.assertEqual(r["summary"]["windows_with_both_candidate_scans"],0)
        self.assertEqual(r["summary"]["source_status_counts"],{"CAPTURE_PENDING":2})
    def test_unrecognized_or_malformed_response_rejected(self):
        for obj in ({"stat":"error","data":[]},
                    {"stat":"OK","fields":["wrong"],"data":[]},
                    {"stat":"OK","fields":["股票代號","除權息日期"],"data":[["2330"]]}):
            with self.assertRaises(ValueError):
                parse(json.dumps(obj).encode(),"ex")
    def test_queue_tampering_rejected_before_lookup(self):
        a,p=self.inputs()
        p["private_action_windows"][0]["entry_date"]="2024-05-03"
        with self.assertRaises(ValueError):
            scan(a,p,lambda *args:self.fail("Tampered plan reached network"))

    def test_explicit_reduction_no_match_never_certifies_zero_actions(self):
        raw=json.dumps({"stat":"很抱歉，沒有符合條件的資料!"}).encode()
        self.assertEqual(parse_response(raw,"reduction"),([],"OFFICIAL_REDUCTION_NO_MATCH_ONLY"))
        with self.assertRaises(ValueError):
            parse_response(raw,"ex")
        a,p=self.inputs()
        r=scan(a,p,lambda kind,start,end: (self.rows(),"a"*64,"CANDIDATE_SCAN_ONLY")
               if kind=="ex" else ([],"b"*64,"OFFICIAL_REDUCTION_NO_MATCH_ONLY"))
        m=r["summary"]
        self.assertEqual(m["windows_with_both_candidate_scans"],1)
        self.assertEqual(m["windows_with_both_non_no_match_scans"],0)
        self.assertEqual(m["source_status_counts"]["OFFICIAL_REDUCTION_NO_MATCH_ONLY"],1)
        self.assertTrue(m["reduction_no_match_is_not_zero_action_proof"])
        self.assertFalse(m["corporate_action_coverage_verified"])
        self.assertEqual(m["approved_total_return_labels"],0)

    def test_unknown_error_or_nonempty_no_match_rejected(self):
        for body in ({"stat":"很抱歉，系統忙碌"},
                     {"stat":"查無資料","data":[["unexpected"]]},
                     {"stat":"error","data":[]}):
            with self.assertRaises(ValueError):
                parse_response(json.dumps(body).encode(),"reduction")
