import json
import unittest
from scripts.v3_stock_month_gap_evidence import parse_month,audit_queue
from scripts.v3_gap_action_review_plan import build_review
from scripts.v3_raw_path_overlap_audit import digest

class StockMonthGapEvidenceTests(unittest.TestCase):
    def raw(self):
        return {"stat":"OK","title":"113年05月 2317 鴻海 各日成交資訊",
                "fields":["日期","成交股數","成交金額","開盤價","最高價","最低價","收盤價"],
                "data":[["113/05/02","1,000","100000","100","100","100","100.00"],
                        ["113/05/03","0","0","--","--","--","--"]]}
    def test_parse_exact_month_and_missing_close(self):
        rows,kind=parse_month(json.dumps(self.raw()).encode(),"2317","2024-05")
        self.assertEqual(rows,{"2024-05-02":"100.00","2024-05-03":None})
        self.assertEqual(kind,"DATED_MONTH_RESPONSE")
    def test_wrong_issuer_month_and_duplicate_rejected(self):
        raw=self.raw()
        with self.assertRaises(ValueError):
            parse_month(json.dumps(raw).encode(),"2330","2024-05")
        with self.assertRaises(ValueError):
            parse_month(json.dumps(raw).encode(),"2317","2024-06")
        raw["data"].append(raw["data"][0])
        with self.assertRaises(ValueError):
            parse_month(json.dumps(raw).encode(),"2317","2024-05")
    def inputs(self):
        sessions=["2024-05-02","2024-05-03","2024-05-06","2024-05-07","2024-05-08","2024-05-09"]
        paths=[dict(market="twse",stock_id="2330",signal_date="2024-04-30",
                    sessions=sessions,raw_closes=["100"]*6,approved_total_return=False,
                    execution_label_approved=False,corporate_action_coverage_verified=False)]
        gaps=[dict(market="twse",stock_id="2317",signal_date="2024-04-30",
                   reason="MISSING_STOCK_CLOSE",missing_sessions=sessions[:2])]
        summary=dict(scope="V3_FINAL_RAW_PATH_RESEARCH_ONLY",offline_replay_verified=True,model_release="BLOCKED",
            approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
            available_path_rows=1,remaining_rows=1,joined_rows=2,raw_paths_sha256=digest(paths),
            remaining_keys_sha256=digest(gaps),cutoff="2024-07-01",available_signal_dates=1,
            missing_stock_close_rows=1,not_yet_mature_rows=0)
        audit=dict(summary=summary,private_raw_paths=paths,private_remaining_keys=gaps)
        return audit,build_review(audit)
    def test_pending_and_partial_evidence(self):
        a,p=self.inputs()
        r=audit_queue(a,p,lambda s,m:None)
        self.assertEqual(r["summary"]["counts"],{"CAPTURE_PENDING":2})
        r=audit_queue(a,p,lambda s,m:({"2024-05-02":"100"},"DATED_MONTH_RESPONSE","a"*64))
        self.assertEqual(r["summary"]["fully_supported_missing_date_paths"],0)
        self.assertEqual(r["summary"]["counts"],{"POSITIVE_CLOSE_CANDIDATE":1,"DATE_NOT_IN_MONTH_RESPONSE":1})
        self.assertEqual(r["summary"]["confirmed_halt_rows"],0)
    def test_complete_candidates_not_approved(self):
        a,p=self.inputs()
        r=audit_queue(a,p,lambda s,m:({"2024-05-02":"100","2024-05-03":"101"},"DATED_MONTH_RESPONSE","a"*64))
        self.assertEqual(r["summary"]["fully_supported_missing_date_paths"],1)
        self.assertEqual(r["summary"]["execution_labels_approved"],0)
        self.assertFalse(r["summary"]["original_paths_modified"])
        p["private_stock_month_queue"][0]["stock_id"]="1589"
        with self.assertRaises(ValueError):
            audit_queue(a,p,lambda s,m:self.fail("tampered queue reached lookup"))
