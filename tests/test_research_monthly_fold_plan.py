from datetime import date,timedelta
import unittest
from src import research_monthly_fold_plan as m

def fixture(count):
    result=[]
    for i in range(count):
        d=date(2022,12,1)+timedelta(days=30*i)
        result.append({"signal_date":d.isoformat(),"entry_date":(d+timedelta(days=1)).isoformat(),
            "exit_date":(d+timedelta(days=8)).isoformat(),"candidate_rows":5,
            "complete_label_rows":5,"whole_cohort_aligned":True,
            "label_kind":"HYPOTHETICAL_ECONOMIC_RESEARCH_ONLY"})
    return result

class FoldTests(unittest.TestCase):
    def test_preserve_twenty_training_dates(self):
        a=fixture(48)
        r=m.plan(a,label_cutoff="2027-01-01",test_start=a[20]["signal_date"])
        self.assertEqual(r["test_windows"],28)
        self.assertTrue(r["exploratory_date_count_gate"])
        self.assertFalse(r["model_trained"])
        for f in r["folds"]:
            self.assertGreaterEqual(f["training_dates"],20)
            self.assertLess(f["last_mature_training_exit"],f["signal_date"])
        self.assertEqual(r["model_release"],"BLOCKED")

    def test_quarterly_insufficient(self):
        a=fixture(17)
        self.assertEqual(m.plan(a,label_cutoff="2027-01-01",test_start=a[10]["signal_date"])["test_windows"],0)

    def test_maturity_and_whole_cohort(self):
        a=fixture(31)
        a[0]["complete_label_rows"]=4
        a[1]["exit_date"]=a[20]["signal_date"]
        r=m.plan(a,label_cutoff="2027-01-01",test_start=a[20]["signal_date"])
        self.assertGreaterEqual(r["exclusions"]["insufficient_mature_training"],2)
        self.assertFalse(r["exploratory_date_count_gate"])
        a.append(a[0])
        with self.assertRaises(ValueError):
            m.plan(a,label_cutoff="2027-01-01",test_start=a[20]["signal_date"])
