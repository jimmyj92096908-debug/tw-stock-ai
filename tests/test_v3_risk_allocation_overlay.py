"""Synthetic tests for incremental ERC overlay; no market performance claims."""
import unittest
from datetime import date,timedelta
from src.v3_risk_allocation_overlay import allocate_with_risk_overlay

PROTOCOL="a"*64


class RiskOverlayTests(unittest.TestCase):
    def prediction(self,s,sector="tech"):
        return dict(market="TWSE",stock_id=s,currently_listed=True,
                    signal_date="2024-05-01",training_labels_through="2024-04-30",
                    probability=0.85,stop_loss_fraction=0.05,sector=sector,
                    protocol_sha256=PROTOCOL)

    def outcomes(self):
        start=date(2024,1,2)
        return [dict(market="TWSE",stock_id=str(2300+j),currently_listed=True,
                     signal_date=(start+timedelta(days=i)).isoformat(),
                     exit_date=(start+timedelta(days=i+1)).isoformat(),
                     training_labels_through=(start+timedelta(days=i-1)).isoformat(),
                     probability=0.85,net_return=0.06 if j<4 else -0.02,
                     protocol_sha256=PROTOCOL)
                for i in range(100) for j in range(5)]

    def history(self,s,pattern):
        start=date(2024,2,27)
        return dict(market="TWSE",stock_id=s,currently_listed=True,
                    returns=[{"date":(start+timedelta(days=i)).isoformat(),
                              "return":pattern[i%len(pattern)]} for i in range(64)])

    def run_case(self,**kw):
        args=dict(decision_date="2024-05-01",protocol_sha256=PROTOCOL,
                  predictions=[self.prediction("2401"),self.prediction("2402")],
                  outcomes=self.outcomes(),existing_positions=[],cash_available=1,
                  drawdown=0,regime="UPTREND",volatile_heuristic=False,
                  histories=[self.history("2401",[.01,-.01]),
                             self.history("2402",[.02,.02,-.02,-.02])])
        args.update(kw)
        return allocate_with_risk_overlay(**args)

    def test_uniform_erc_scaling_never_increases_caps(self):
        r=self.run_case()
        self.assertEqual(r["status"],"INCREMENTAL_ERC_OVERLAY")
        self.assertAlmostEqual(r["weights"]["2401"],.1)
        self.assertAlmostEqual(r["weights"]["2402"],.05)
        self.assertAlmostEqual(r["research_incremental_total"],.15)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["whole_account_erc_verified"])

    def test_existing_correlated_candidate_blocked(self):
        existing=[dict(self.prediction("2400"),account_weight=.1,
                       remaining_stop_risk_fraction=.05)]
        r=self.run_case(existing_positions=existing,cash_available=.9,
                        histories=[self.history("2400",[.03,-.03]),
                                   self.history("2401",[.01,-.01]),
                                   self.history("2402",[.02,.02,-.02,-.02])])
        self.assertEqual(r["blocked_correlated_candidates"],["2401"])
        self.assertEqual(set(r["weights"]),{"2402"})
        self.assertEqual(r["status"],"SINGLE_CANDIDATE_NO_ERC")

    def test_missing_and_stale_history_blocks(self):
        self.assertEqual(self.run_case(histories=[])["research_incremental_total"],0)
        h=self.history("2401",[.01,-.01])
        h["returns"]=[dict(x,date=(date.fromisoformat(x["date"])-timedelta(days=15)).isoformat())
                      for x in h["returns"]]
        r=self.run_case(histories=[h,self.history("2402",[.02,-.02])])
        self.assertEqual(r["status"],"RISK_HISTORY_STALE")
        self.assertEqual(r["weights"],{})

    def test_no_evidence_and_single_candidate(self):
        self.assertEqual(self.run_case(outcomes=[],histories=[])["status"],
                         "NO_ELIGIBLE_CANDIDATES")
        r=self.run_case(predictions=[self.prediction("2401")])
        self.assertAlmostEqual(r["weights"]["2401"],.1)
        self.assertIsNone(r["risk_reference"])

    def test_unaligned_and_duplicate_history_rejected(self):
        h=self.history("2401",[.01,-.01])
        with self.assertRaises(ValueError):
            self.run_case(histories=[h,h])
        h["returns"][0]["date"]="2024-02-26"
        with self.assertRaises(ValueError):
            self.run_case(histories=[h,self.history("2402",[.02,-.02])])


if __name__=="__main__":
    unittest.main()
