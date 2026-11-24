import copy
import unittest
from src import research_entitlement_return as m

DAYS=["2026-09-01","2026-09-02","2026-09-03","2026-09-04","2026-09-07","2026-09-08"]
HASH="a"*64

def event(day,kind,cash,shares):
    return {"event_id":day,"ex_date":day,"kind":kind,"cash_per_pre_event_share":cash,
            "shares_per_pre_event_share":shares,"evidence_sha256":HASH}

def fixture(sid="2330",exit_price="100"):
    return {"market":"twse","stock_id":sid,"signal_date":"2026-08-31","sessions":DAYS[:],
        "prices":[{"trade_date":d,"close":exit_price if d==DAYS[-1] else "100","evidence_sha256":HASH} for d in DAYS],
        "actions":[],"coverage":{"market":"twse","stock_id":sid,"start_exclusive":DAYS[0],
            "end_inclusive":DAYS[-1],"all_action_types_covered_asserted":True,"evidence_sha256":HASH}}

class EntitlementTests(unittest.TestCase):
    def test_cash_and_split_order(self):
        x=fixture(exit_price="49")
        x["actions"]=[event(DAYS[1],"STOCK_SPLIT","0","2"),event(DAYS[-1],"CASH_DIVIDEND","1","1")]
        r=m.hypothetical_return(**x)
        self.assertEqual(r["raw_price_return"],"-0.510000000000")
        self.assertEqual(r["cash_entitlement_per_initial_share"],"2.000000000000")
        self.assertEqual(r["hypothetical_gross_entitlement_return"],"0.000000000000")
        self.assertFalse(r["historical_total_return_verified"])
        x=fixture(exit_price="49")
        x["actions"]=[event(DAYS[1],"CASH_DIVIDEND","1","1"),event(DAYS[-1],"STOCK_SPLIT","0","2")]
        self.assertEqual(m.hypothetical_return(**x)["hypothetical_gross_entitlement_return"],"-0.010000000000")

    def test_stock_and_reverse_split(self):
        x=fixture(exit_price="80")
        x["actions"]=[event(DAYS[1],"STOCK_DIVIDEND","0","1.25")]
        self.assertEqual(m.hypothetical_return(**x)["hypothetical_gross_entitlement_return"],"0.000000000000")
        x=fixture(exit_price="200")
        x["actions"]=[event(DAYS[1],"REVERSE_SPLIT","0","0.5")]
        self.assertEqual(m.hypothetical_return(**x)["hypothetical_gross_entitlement_return"],"0.000000000000")

    def test_fail_closed(self):
        for change in (
            lambda x:x["coverage"].__setitem__("all_action_types_covered_asserted",False),
            lambda x:x["actions"].append(event(DAYS[0],"CASH_DIVIDEND","1","1")),
            lambda x:x["actions"].append(event(DAYS[1],"CAPITAL_REDUCTION","1","0.5")),
            lambda x:x["actions"].extend([event(DAYS[1],"CASH_DIVIDEND","1","1"),event(DAYS[1],"STOCK_DIVIDEND","0","1.1")]),
            lambda x:x["prices"][0].__setitem__("close","NaN"),
            lambda x:x["prices"][0].__setitem__("close","0"),
            lambda x:x["prices"].pop(2),
            lambda x:x.__setitem__("stock_id","1589"),
        ):
            x=fixture();change(x)
            with self.assertRaises(ValueError):
                m.hypothetical_return(**x)

    def test_whole_cohort_and_maturity(self):
        stocks=["2330","2317","2454","2308","2881"]
        keys=[("twse",s) for s in stocks];rows=[fixture(s) for s in stocks]
        report,result=m.whole_cohort(keys,rows,label_cutoff=DAYS[-1])
        self.assertEqual(len(result),5)
        self.assertEqual(report["approved_total_return_labels"],0)
        self.assertEqual(report["model_release"],"BLOCKED")
        with self.assertRaises(ValueError):
            m.whole_cohort(keys,rows[:-1],label_cutoff=DAYS[-1])
        with self.assertRaises(ValueError):
            m.whole_cohort(keys,rows,label_cutoff=DAYS[-2])
        bad=copy.deepcopy(rows);bad[-1]["actions"]=[event(DAYS[1],"OTHER","0","1")]
        with self.assertRaises(ValueError):
            m.whole_cohort(keys,bad,label_cutoff=DAYS[-1])
