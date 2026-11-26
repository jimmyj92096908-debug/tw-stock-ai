"""Synthetic end-to-end research replay; no real market performance claims."""
import unittest
from datetime import date,timedelta
from src.v3_allocated_portfolio_replay import replay_allocated_portfolio

PROTOCOL="a"*64


class AllocatedReplayTests(unittest.TestCase):
    def sessions(self):
        return [{"date":d,"bars":{"2401":{"market":"TWSE",
                 "currently_listed":True,"corporate_action_clear":True,
                 "open":10,"high":10,"low":10,"close":10,
                 "buy_eligible":True,"sell_eligible":True,
                 "buy_capacity_shares":100000,"sell_capacity_shares":100000}}}
                for d in ("2024-05-01","2024-05-02","2024-05-03","2024-05-06")]

    def evidence(self):
        start=date(2024,1,2)
        hstart=date(2024,2,27)
        return {"predictions":[dict(stock_id="2401",market="TWSE",currently_listed=True,
                    signal_date="2024-05-01",training_labels_through="2024-04-30",
                    probability=.85,stop_loss_fraction=.05,sector="tech",protocol_sha256=PROTOCOL)],
                "outcomes":[dict(stock_id=str(2300+j),market="TWSE",currently_listed=True,
                    signal_date=(start+timedelta(days=i)).isoformat(),
                    exit_date=(start+timedelta(days=i+1)).isoformat(),
                    training_labels_through=(start+timedelta(days=i-1)).isoformat(),
                    probability=.85,net_return=.06 if j<4 else -.02,protocol_sha256=PROTOCOL)
                    for i in range(100) for j in range(5)],
                "histories":[dict(stock_id="2401",market="TWSE",currently_listed=True,
                    returns=[{"date":(hstart+timedelta(days=i)).isoformat(),
                              "return":.01 if i%2 else -.01} for i in range(64)])],
                "regime":"UPTREND","volatile_heuristic":False}

    def run_case(self, rows=None, evidence=None, **kw):
        args=dict(protocol_sha256=PROTOCOL,sector_by_stock={"2401":"tech"},
                  commission=0,sell_tax=0,slippage=0,
                  daily_evidence={"2024-05-01":self.evidence()} if evidence is None else evidence)
        args.update(kw)
        return replay_allocated_portfolio(self.sessions() if rows is None else rows,**args)

    def test_next_session_entry_and_no_forced_liquidation(self):
        r=self.run_case()
        self.assertEqual(len(r["fills"]),1)
        self.assertEqual(r["fills"][0]["date"],"2024-05-02")
        self.assertEqual(r["fills"][0]["shares"],10000)
        self.assertEqual(r["path"][0]["holdings"],{})
        self.assertEqual(r["path"][-1]["holdings"],{"2401":10000})
        self.assertAlmostEqual(r["net_marked_return"],0)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertTrue(r["incremental_allocator_integrated"])
        self.assertFalse(r["real_model_trained"])

    def test_missing_evidence_and_history_abstain(self):
        self.assertEqual(self.run_case(evidence={})["fills"],[])
        e=self.evidence()
        e["histories"]=[]
        self.assertEqual(self.run_case(evidence={"2024-05-01":e})["fills"],[])

    def test_frozen_budget_does_not_expand_and_stop_settles(self):
        rows=self.sessions()
        rows[1]["bars"]["2401"].update(open=20,high=20,low=20,close=20)
        rows[2]["bars"]["2401"].update(open=16,high=16,low=16,close=16)
        r=self.run_case(rows)
        self.assertEqual(r["fills"][0]["shares"],5000)
        self.assertEqual(r["fills"][1]["reason"],"GAP_STOP")
        self.assertEqual(r["path"][2]["unsettled_sale_proceeds"],80000)
        self.assertAlmostEqual(r["net_marked_return"],-.02)

    def test_cost_inclusive_risk_reduces_budget(self):
        r=self.run_case(commission=.001425,sell_tax=.003,slippage=.001)
        self.assertLess(r["incremental_allocation_log"][0]["weights"]["2401"],.1)
        self.assertLess(r["fills"][0]["shares"],10000)

    def test_future_outcomes_and_external_targets_rejected(self):
        e=self.evidence()
        e["outcomes"][-1]["exit_date"]="2024-05-01"
        with self.assertRaises(ValueError):
            self.run_case(evidence={"2024-05-01":e})
        rows=self.sessions()
        rows[0]["close_targets"]={"2401":.1}
        with self.assertRaises(ValueError):
            self.run_case(rows)
        with self.assertRaises(ValueError):
            self.run_case(evidence={"2024-05-07":self.evidence()})


if __name__=="__main__":
    unittest.main()
