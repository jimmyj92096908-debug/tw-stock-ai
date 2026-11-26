"""Synthetic market-regime chronology and diagnostic tests."""
import unittest
from datetime import date,timedelta
from src.v3_market_regime_archive import market_regime_archive,regime_outcome_diagnostics


class MarketRegimeArchiveTests(unittest.TestCase):
    def rows(self,kind="up"):
        start=date(2024,1,1)
        return [dict(date=(start+timedelta(days=i)).isoformat(),
                     available_date=(start+timedelta(days=i)).isoformat(),
                     index_id="TWSE_TAIEX",source_declared_official=True,vintage_declared=True,
                     close=10000+i*20 if kind=="up" else 10000-i*20 if kind=="down" else 10000)
                for i in range(100)]

    def test_trend_and_unknown(self):
        for kind,state in (("up","UPTREND"),("down","DOWNTREND"),("flat","RANGE_OR_TRANSITION")):
            with self.subTest(kind=kind):
                r=market_regime_archive(index_rows=self.rows(kind),decision_dates=["2024-01-02","2024-04-01"])
                self.assertEqual(r["states"][0]["regime"],"UNKNOWN_HISTORY")
                self.assertEqual(r["states"][1]["regime"],state)
                self.assertFalse(r["states"][1]["volatile_heuristic"])
                self.assertFalse(r["trading_approved"])

    def test_late_close_and_future_mutation(self):
        rows=self.rows()
        a=market_regime_archive(index_rows=rows,decision_dates=["2024-04-01"])
        for r in rows:
            if r["date"]>"2024-04-01":
                r["close"]=2
        self.assertEqual(a,market_regime_archive(index_rows=rows,decision_dates=["2024-04-01"]))
        next(r for r in rows if r["date"]=="2024-04-01")["available_date"]="2024-04-02"
        b=market_regime_archive(index_rows=rows,decision_dates=["2024-04-01"])
        self.assertEqual(b["states"][0]["regime"],"UNKNOWN_HISTORY")
        self.assertEqual(b["states"][0]["reason"],"CURRENT_CLOSE_UNAVAILABLE")

    def test_invalid_source_and_dates(self):
        rows=self.rows()
        rows[0]["index_id"]="2330"
        with self.assertRaises(ValueError):
            market_regime_archive(index_rows=rows,decision_dates=["2024-04-01"])
        with self.assertRaises(ValueError):
            market_regime_archive(index_rows=self.rows(),decision_dates=["2024-04-02","2024-04-01"])

    def test_mature_diagnostics_only(self):
        regimes=market_regime_archive(index_rows=self.rows(),decision_dates=["2024-04-01","2024-04-02"])
        rows=[dict(signal_date=d,training_labels_through="2024-03-31",
                   exit_date="2024-04-03",label_available_date="2024-04-03",
                   cohort_available_date=a,protocol_sha256="a"*64,
                   market="TWSE",stock_id="2330",probability=.9,net_return=n)
              for d,a,n in (("2024-04-01","2024-04-04",.05),("2024-04-02","2024-04-06",-.02))]
        archive=dict(archive_cutoff="2024-04-10",protocol_sha256="a"*64,mature_outcomes=rows)
        r=regime_outcome_diagnostics(archive=archive,regimes=regimes,decision_date="2024-04-06")
        self.assertEqual(r["groups"][0]["observations"],1)
        self.assertEqual(r["groups"][0]["screened_win_rate"],1.)
        self.assertFalse(r["regime_weights_selected"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_high_volatility_flag(self):
        rows=self.rows()
        for i,r in enumerate(rows):
            r["close"]=10000*(1.05 if i%2 else .95)
        r=market_regime_archive(index_rows=rows,decision_dates=["2024-04-01"])
        self.assertTrue(r["states"][0]["volatile_heuristic"])


if __name__=="__main__":
    unittest.main()
