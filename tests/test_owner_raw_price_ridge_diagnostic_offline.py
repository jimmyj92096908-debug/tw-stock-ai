from datetime import date,timedelta
from decimal import Decimal
import unittest
from scripts import owner_raw_price_ridge_diagnostic_offline as m

class RawDiagnosticTests(unittest.TestCase):
    def fixture(self):
        ids=("1101","1231","2308","2330","2454")
        day=date(2023,1,1);rows=[];months={}
        while day<=m.b.CUTOFF:
            if day.weekday()<5:
                months[day.year,day.month]=day
                for i,s in enumerate(ids):
                    p=Decimal(100)+Decimal((day.toordinal()*(i+1))%31)/10
                    rows.append(dict(market="twse",stock_id=s,trade_date=day,source="TWSE_STOCK_DAY",
                        open=p,high=p+1,low=p-1,close=p,volume=100000))
            day+=timedelta(days=1)
        features=[dict(market="twse",stock_id=s,signal_date=d.isoformat(),feature_vector=[float(i)]*12,
                       prefix_source_rows=240,prefix_source_sha256="a"*64)
                  for d in months.values() for i,s in enumerate(ids)]
        return ids,features,rows
    def test_train_only_raw_and_no_future(self):
        ids,features,rows=self.fixture()
        r,paths=m.evaluate(ids,features,rows)
        self.assertTrue(r["raw_price_only_model_trained"])
        self.assertGreaterEqual(r["evaluated_test_windows"],10)
        self.assertEqual(r["approved_total_return_labels"],0)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertTrue(all(f["last_mature_training_exit"]<f["signal_date"] for f in r["folds"]))
        self.assertTrue(all(p["action_coverage_status"]=="NOT_VERIFIED" for p in paths))
        self.assertTrue(all(p["sessions"][-1]<=m.b.CUTOFF.isoformat() for p in paths))
    def test_missing_cohort_and_duplicate_price(self):
        ids,features,rows=self.fixture()
        data,paths,excluded=m.build_paths(ids,features[1:],rows)
        self.assertIn("INCOMPLETE_FEATURE_COHORT",excluded.values())
        with self.assertRaises(ValueError):m.build_paths(ids,features,rows+[rows[0]])
