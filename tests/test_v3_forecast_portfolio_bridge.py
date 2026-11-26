"""Synthetic forecast archive to account replay integration tests."""
import unittest
from src.v3_forecast_portfolio_bridge import replay_forecast_archive
from src.v3_purged_logistic_baseline import _hash
from tests import test_v3_allocated_portfolio_replay as fixtures


class ForecastPortfolioBridgeTests(unittest.TestCase):
    def args(self):
        f=fixtures.AllocatedReplayTests()
        e=f.evidence()
        outcomes=[dict(r,label_available_date=r["exit_date"],
                       cohort_available_date=r["exit_date"]) for r in e["outcomes"]]
        fields=("stock_id","market","currently_listed","signal_date",
                "training_labels_through","probability","protocol_sha256")
        predictions=[{k:r[k] for k in fields} for r in outcomes+e["predictions"]]
        archive=dict(archive_cutoff="2024-05-07",protocol_sha256=fixtures.PROTOCOL,
                     predictions=predictions,mature_outcomes=outcomes,
                     forecast_sha256=_hash(predictions))
        states=[dict(signal_date="2024-05-01",regime="UPTREND",
                     volatile_heuristic=False,last_available_close="2024-05-01")]
        regimes=dict(index_id="TWSE_TAIEX",states=states,states_sha256=_hash(states))
        return dict(sessions=f.sessions(),archive=archive,regimes=regimes,
                    histories_by_date={"2024-05-01":e["histories"]},
                    sector_by_stock={"2401":"tech"},commission=0,sell_tax=0,slippage=0)

    def test_forecast_to_next_open_fill(self):
        r=replay_forecast_archive(**self.args())
        self.assertTrue(r["forecast_archive_integrated"])
        self.assertEqual(r["evidence_log"][0]["mature_outcome_count"],500)
        self.assertEqual(r["fills"][0]["date"],"2024-05-02")
        self.assertEqual(r["fills"][0]["shares"],10000)
        self.assertFalse(r["label_execution_parity_verified"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_same_day_maturity_excluded(self):
        a=self.args()
        rows=a["archive"]["mature_outcomes"]
        for r in rows[-5:]:
            r["label_available_date"]=r["cohort_available_date"]="2024-05-01"
        result=replay_forecast_archive(**a)
        self.assertEqual(result["evidence_log"][0]["mature_outcome_count"],495)
        self.assertEqual(result["fills"],[])

    def test_unknown_regime_blocks_new_exposure(self):
        a=self.args()
        a["regimes"]["states"][0]["regime"]="UNKNOWN_HISTORY"
        a["regimes"]["states_sha256"]=_hash(a["regimes"]["states"])
        self.assertEqual(replay_forecast_archive(**a)["fills"],[])

    def test_digest_and_partial_cohort_rejected(self):
        a=self.args()
        a["archive"]["predictions"][-1]["probability"]=.99
        with self.assertRaises(ValueError):
            replay_forecast_archive(**a)
        a=self.args()
        a["archive"]["mature_outcomes"].pop()
        with self.assertRaises(ValueError):
            replay_forecast_archive(**a)

    def test_missing_regime_and_mismatched_outcome_rejected(self):
        a=self.args()
        a["regimes"]["states"]=[]
        a["regimes"]["states_sha256"]=_hash([])
        with self.assertRaises(ValueError):
            replay_forecast_archive(**a)
        a=self.args()
        a["archive"]["mature_outcomes"][0]["probability"]=.9
        with self.assertRaises(ValueError):
            replay_forecast_archive(**a)


if __name__=="__main__":
    unittest.main()
