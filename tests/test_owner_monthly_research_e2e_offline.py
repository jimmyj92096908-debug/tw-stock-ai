from datetime import date,timedelta
import copy
import unittest
from scripts import owner_monthly_research_e2e_offline as e
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m

def fixture():
    ids=["2300","2301","2302","2303","2304"]
    rows=[];obs=[];outcomes=[]
    anchors={(date.fromisoformat(d).year,date.fromisoformat(d).month):d for d in m.DATES}
    for y,month in e.MONTHS:
        d=date(y,month,20)
        while d.weekday()>=5:d-=timedelta(days=1)
        s=anchors.get((y,month),d.isoformat());d=date.fromisoformat(s)
        outcomes.append({"signal_date":s,"accepted":5,"excluded":{}})
        sessions=[];x=d
        while len(sessions)<6:
            x+=timedelta(days=1)
            if x.weekday()<5:sessions.append(x.isoformat())
        for j,sid in enumerate(ids):
            rows.append({"market":"twse","stock_id":sid,"signal_date":s,"feature_vector":[float(j)]*12,
                "prefix_source_rows":240,"prefix_source_sha256":"a"*64})
            if s==e.CUTOFF:continue
            obs.append({"market":"twse","stock_id":sid,"signal_date":s,"sessions":sessions,
                "prices":[{"trade_date":t,"close":str(100+j) if t==sessions[-1] else "100","evidence_sha256":"a"*64} for t in sessions],
                "actions":[],"coverage":{"market":"twse","stock_id":sid,"start_exclusive":sessions[0],
                    "end_inclusive":sessions[-1],"all_action_types_covered_asserted":True,"evidence_sha256":"b"*64}})
    q=[r for r in rows if r["signal_date"] in m.DATES]
    summary={"schema_version":1,"scope":"OWNER_MONTHLY_RAW_FEATURE_PILOT_OFFLINE","market":"twse",
        "candidate_stocks":5,"requested_signal_dates":48,"candidate_stock_signal_pairs":240,
        "accepted_feature_rows":240,"accepted_feature_values":2880,"feature_version":m.VERSION,
        "feature_names":m.FEATURES,"quarterly_anchor_exact":True,"quarterly_anchor_rows_replayed":len(q),
        "quarterly_anchor_sha256":m.fingerprint(q),"private_feature_rows_sha256":m.fingerprint(rows),
        "signal_date_outcomes":outcomes,"prefix_only_feature_computation":True,
        "official_market_calendar_independently_proven":False,"current_roster_not_historical_pit":True,
        "forward_labels_created":False,"corporate_actions_adjusted":False,"model_trained":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED"}
    return {"summary":summary,"sample_stock_ids":ids,"private_feature_rows":rows}, {
        "schema_version":1,"scope":"OWNER_HYPOTHETICAL_ECONOMIC_OBSERVATIONS","observations":obs,
        "excluded_signal_dates":{e.CUTOFF:"UNMATURED_AT_CUTOFF"}},q

class E2ETests(unittest.TestCase):
    def test_end_to_end(self):
        p,o,q=fixture()
        r=e.evaluate_bundle(p,o,q,test_start="2024-09-01")
        self.assertTrue(r["summary"]["hypothetical_model_fitted"])
        self.assertGreaterEqual(r["summary"]["test_windows"],10)
        self.assertEqual(r["summary"]["approved_total_return_labels"],0)
        self.assertEqual(r["summary"]["model_release"],"BLOCKED")

    def test_missing_or_tampered(self):
        p,o,q=fixture()
        bad=copy.deepcopy(o);bad["observations"].pop(0)
        with self.assertRaises(ValueError):e.evaluate_bundle(p,bad,q,test_start="2024-09-01")
        bad=copy.deepcopy(p);bad["private_feature_rows"][0]["feature_vector"][0]=999
        bad["summary"]["private_feature_rows_sha256"]=m.fingerprint(bad["private_feature_rows"])
        with self.assertRaises(ValueError):e.evaluate_bundle(bad,o,q,test_start="2024-09-01")
        bad=copy.deepcopy(o);bad["excluded_signal_dates"]["2022-12-30"]="ACTION_COVERAGE_UNPROVEN"
        with self.assertRaises(ValueError):e.evaluate_bundle(p,bad,q,test_start="2024-09-01")
