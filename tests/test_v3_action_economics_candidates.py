import copy
import unittest
from decimal import Decimal
from scripts.v3_action_economics_candidates import cash_candidate,economics
from scripts.v3_gap_action_review_plan import build_review
from scripts.v3_raw_path_overlap_audit import digest
from scripts.v3_twse_action_candidate_scan import scan

class ActionEconomicsTests(unittest.TestCase):
    def fixture(self):
        sessions=["2024-05-02","2024-05-03","2024-05-06","2024-05-07","2024-05-08","2024-05-09"]
        paths=[dict(market="twse",stock_id="2330",signal_date="2024-04-30",
                    sessions=sessions,raw_closes=["100"]*5+["98"],approved_total_return=False,
                    execution_label_approved=False,corporate_action_coverage_verified=False)]
        gaps=[]
        summary=dict(scope="V3_FINAL_RAW_PATH_RESEARCH_ONLY",offline_replay_verified=True,model_release="BLOCKED",
             approved_total_return_labels=0,execution_labels_approved=0,approved_training_feature_rows=0,
             available_path_rows=1,remaining_rows=0,joined_rows=1,raw_paths_sha256=digest(paths),
             remaining_keys_sha256=digest(gaps),cutoff="2024-07-01",available_signal_dates=1,
             missing_stock_close_rows=0,not_yet_mature_rows=0)
        a=dict(summary=summary,private_raw_paths=paths,private_remaining_keys=gaps)
        return a,build_review(a)
    def event(self,d,raw):
        return dict(stock_id="2330",event_date=d,kind="ex",raw_record=raw,source_row_sha256=digest(raw))
    def run_economics(self,events):
        a,p=self.fixture()
        def lookup(kind,start,end):
            return (events,"a"*64,"CANDIDATE_SCAN_ONLY") if kind=="ex" else ([],"b"*64,"OFFICIAL_REDUCTION_NO_MATCH_ONLY")
        saved=scan(a,p,lookup)
        return economics(a,p,saved,lookup)
    def test_explicit_cash_only(self):
        self.assertEqual(cash_candidate(dict(kind="ex",raw_record={"權/息":"息","每股現金股利":"3.50"})),
                         ("EXPLICIT_CASH_CANDIDATE",Decimal("3.50")))
        self.assertEqual(cash_candidate(dict(kind="ex",raw_record={"權/息":"息","息值":"3.50"})),
                         ("EXPLICIT_CASH_NOT_AVAILABLE",None))
        self.assertEqual(cash_candidate(dict(kind="ex",raw_record={"權/息":"權息","每股現金股利":"3.50"}))[1],None)
    def test_holding_cash_arithmetic_and_entry_exclusion(self):
        raw={"權/息":"息","每股現金股利":"3"}
        r=self.run_economics([self.event("2024-05-02",raw),self.event("2024-05-03",raw)])
        row=r["private_candidate_paths"][0]
        self.assertEqual(Decimal(row["cash_entitlement_gross_return_candidate"]),Decimal(".01"))
        self.assertEqual(r["summary"]["mean_gross_cash_delta_supported_paths"],.03)
        self.assertFalse(row["approved_total_return"])
        self.assertEqual(r["summary"]["execution_labels_approved"],0)
    def test_unknown_duplicate_and_non_session_block_arithmetic(self):
        raw={"權/息":"息","每股現金股利":"3"}
        ev=self.event("2024-05-03",raw)
        for events in ([ev,copy.deepcopy(ev)],[ev,self.event("2024-05-04",raw)],
                       [ev,self.event("2024-05-06",{"權/息":"權"})]):
            r=self.run_economics(events)
            self.assertEqual(r["private_candidate_paths"][0]["status"],"UNRESOLVED_EVENT_TERMS_OR_CALENDAR")
            self.assertIsNone(r["private_candidate_paths"][0]["cash_entitlement_gross_return_candidate"])
    def test_no_events_not_approved(self):
        r=self.run_economics([])
        self.assertEqual(r["summary"]["paths_without_detected_events"],1)
        self.assertFalse(r["summary"]["missing_event_implies_no_action"])
        self.assertEqual(r["summary"]["approved_total_return_labels"],0)
    def test_replay_mismatch_rejected(self):
        a,p=self.fixture()
        def lookup(*args):
            return [],"a"*64,"CANDIDATE_SCAN_ONLY"
        saved=scan(a,p,lookup)
        saved["summary"]["candidate_event_rows"]=1
        with self.assertRaises(ValueError):
            economics(a,p,saved,lookup)
