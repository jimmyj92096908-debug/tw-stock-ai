import unittest
from datetime import date, timedelta
from src.benchmark_analysis import regime_map

class RegimeMapTests(unittest.TestCase):
    def test_classification_uses_previous_session_close(self):
        start=date(2025,1,1)
        rows=[(start+timedelta(days=i),100.0+i) for i in range(245)]
        regimes=regime_map(rows)
        self.assertNotIn(rows[0][0],regimes)
        self.assertEqual(regimes[rows[220][0]],"BULL")
        self.assertEqual(regimes[rows[221][0]],"BULL")

    def test_early_sessions_are_unknown(self):
        rows=[(date(2025,1,1)+timedelta(days=i),100.0+i) for i in range(10)]
        regimes=regime_map(rows)
        self.assertNotIn(rows[0][0],regimes)
        self.assertTrue(all(v=="UNKNOWN" for v in regimes.values()))

if __name__=="__main__": unittest.main()
