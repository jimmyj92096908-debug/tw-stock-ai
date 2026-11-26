"""Synthetic regression tests for the prediction-to-allocation bridge."""
import unittest
from datetime import date,timedelta
from src.v3_prediction_allocation import allocate_research

PROTOCOL="a"*64


class PredictionAllocationTests(unittest.TestCase):
    def history(self):
        start=date(2024,1,2)
        return [dict(market="TWSE",stock_id=str(2300+j),currently_listed=True,
                     signal_date=(start+timedelta(days=i)).isoformat(),
                     exit_date=(start+timedelta(days=i+1)).isoformat(),
                     training_labels_through=(start+timedelta(days=i-1)).isoformat(),
                     probability=0.85,net_return=0.06 if j<4 else -0.02,
                     protocol_sha256=PROTOCOL)
                for i in range(100) for j in range(5)]

    def prediction(self,s="2400",**kw):
        r=dict(market="TWSE",stock_id=s,currently_listed=True,
               signal_date="2024-05-01",training_labels_through="2024-04-30",
               probability=0.85,stop_loss_fraction=0.05,sector="tech",
               protocol_sha256=PROTOCOL)
        r.update(kw)
        return r

    def allocate(self,**kw):
        args=dict(decision_date="2024-05-01",protocol_sha256=PROTOCOL,
                  predictions=[self.prediction()],outcomes=self.history(),
                  existing_positions=[],cash_available=1,drawdown=0,
                  regime="UPTREND",volatile_heuristic=False)
        args.update(kw)
        return allocate_research(**args)

    def test_positive_hypothesis_never_approves_trades(self):
        r=self.allocate()
        self.assertAlmostEqual(r["research_incremental_total"],0.1)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertFalse(r["trading_approved"])
        self.assertFalse(r["confidence_bound_verified"])

    def test_no_allocation_without_evidence(self):
        for outcomes in ([],self.history()[:-1],
                         [dict(r,net_return=-0.1) for r in self.history()]):
            r=self.allocate(outcomes=outcomes)
            self.assertEqual(r["research_incremental_total"],0)
        self.assertEqual(self.allocate(predictions=[self.prediction(probability=0.95)])
                         ["research_incremental_total"],0)
        self.assertEqual(self.allocate(predictions=[self.prediction(probability=0.79)])
                         ["research_incremental_total"],0)

    def test_shared_budgets_and_existing_positions(self):
        existing=[dict(self.prediction("2400"),account_weight=0.20,
                       remaining_stop_risk_fraction=0.05)]
        candidates=[self.prediction(s) for s in ("2400","2401","2402")]
        r=self.allocate(existing_positions=existing,predictions=candidates,
                        cash_available=0.8)
        self.assertAlmostEqual(r["research_incremental_total"],0.05)
        self.assertEqual(r["candidates"][0]["reason"],"EXISTING_POSITION")
        self.assertAlmostEqual(r["candidates"][1]["incremental_weight"],0.05)
        self.assertEqual(r["candidates"][2]["incremental_weight"],0)
        self.assertEqual(r,self.allocate(existing_positions=existing,
                          predictions=list(reversed(candidates)),cash_available=0.8))

    def test_cash_and_risk_caps(self):
        candidates=[self.prediction(s,sector=s) for s in ("2401","2402","2403")]
        self.assertAlmostEqual(self.allocate(predictions=candidates,cash_available=0.03)
                               ["research_incremental_total"],0.03)
        self.assertAlmostEqual(self.allocate(predictions=candidates,total_stop_risk_limit=0.001)
                               ["research_incremental_total"],0.02)
        for kw in ({"drawdown":0.1},{"regime":"UNKNOWN_HISTORY"}):
            self.assertEqual(self.allocate(**kw)["research_incremental_total"],0)

    def test_protocol_chronology_and_exclusions(self):
        for pred in (self.prediction("1589"),self.prediction(protocol_sha256="b"*64),
                     self.prediction(training_labels_through="2024-05-01")):
            with self.assertRaises(ValueError):
                self.allocate(predictions=[pred])
        rows=self.history()
        rows[-1]["exit_date"]="2024-05-01"
        with self.assertRaises(ValueError):
            self.allocate(outcomes=rows)
        rows=self.history()
        rows[-1]["protocol_sha256"]="b"*64
        with self.assertRaises(ValueError):
            self.allocate(outcomes=rows)


if __name__=="__main__":
    unittest.main()
