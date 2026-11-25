import copy
import json
import unittest
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m

def fixture(market,sid):
    rows=[{"stock_id":sid,"market":market,"signal_date":d,"feature_vector":[0.0]*12,
        "prefix_source_rows":240,"prefix_source_sha256":"a"*64} for d in m.DATES]
    digest=m.fingerprint(rows)
    spec=(1,1,17,digest,[1]*17)
    s={"schema_version":1,"scope":"OWNER_"+market.upper()+"_ALL_CURRENT_LISTED_QUARTERLY_RAW_FEATURE_PANEL",
        "eligible_stocks":1,"batch_count":1,"requested_signal_dates":17,"candidate_stock_signal_pairs":17,
        "accepted_feature_rows":17,"accepted_feature_values":204,"feature_version":m.VERSION,
        "feature_names":m.FEATURES,"private_feature_rows_sha256":digest,"prefix_only_feature_computation":True,
        "current_roster_not_historical_pit":True,"official_market_calendar_independently_proven":False,
        "daily_full_five_year_factor_panel_recomputed":False,"forward_labels_created":False,
        "corporate_actions_adjusted":False,"historical_pit_total_return_verified":False,
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED",
        "signal_date_outcomes":[{"signal_date":d,"accepted":1,"excluded":{}} for d in m.DATES]}
    return {"summary":s,"private_batch_receipts":[{"issuer_count":1,"accepted_rows":17,"feature_rows_sha256":digest}],
        "private_feature_rows":rows},spec

class MergeTests(unittest.TestCase):
    def test_merge(self):
        a,sa=fixture("twse","2330");b,sb=fixture("tpex","6488")
        report,rows=m.merge(a,b,specs={"twse":sa,"tpex":sb})
        self.assertEqual(len(rows),34)
        self.assertEqual(report["accepted_feature_values"],408)
        self.assertEqual(report["production_neon_reads"],0)
        self.assertFalse(report["batch_receipt_hashes_independently_recomputed"])
        self.assertFalse(report["forward_labels_created"])
        self.assertEqual(report["model_release"],"BLOCKED")

    def test_tampering(self):
        a,sa=fixture("twse","2330");b,sb=fixture("tpex","6488")
        for change in (
            lambda x:x["private_feature_rows"][0]["feature_vector"].__setitem__(0,0.1),
            lambda x:x["private_feature_rows"].append(x["private_feature_rows"][0]),
            lambda x:x["private_feature_rows"][0].__setitem__("stock_id","1589"),
            lambda x:x["summary"].__setitem__("model_release","APPROVED"),
            lambda x:x["summary"]["signal_date_outcomes"][0].__setitem__("accepted",0),
            lambda x:x["private_batch_receipts"][0].__setitem__("accepted_rows",16),
            lambda x:x["summary"].__setitem__("production_neon_writes",False),
            lambda x:x["private_feature_rows"][0]["feature_vector"].__setitem__(0,float("nan")),
        ):
            changed=copy.deepcopy(a);change(changed)
            with self.assertRaises(ValueError):
                m.merge(changed,b,specs={"twse":sa,"tpex":sb})
        b,sb=fixture("tpex","2330")
        with self.assertRaises(ValueError):
            m.merge(a,b,specs={"twse":sa,"tpex":sb})

    def test_duplicate_json(self):
        with self.assertRaises(ValueError):
            json.loads('{"a":1,"a":2}',object_pairs_hook=m.strict_object)
        with self.assertRaises(ValueError):
            json.loads('{"a":NaN}',parse_constant=m.reject_constant)
