"""Dataset coverage and maturity audits for execution-aligned labels."""
import unittest
from src.v3_execution_dataset import build_execution_dataset
from tests import test_v3_execution_label_cohort as fixtures


class ExecutionDatasetTests(unittest.TestCase):
    def args(self):
        a=fixtures.ExecutionLabelCohortTests().args()
        cohort={k:a[k] for k in ("sessions","candidates","label_available_date")}
        cohort["signal_date"]="2024-05-01"
        settings={k:v for k,v in a.items() if k not in cohort}
        return dict(expected_signal_dates=["2024-05-01"],cohorts=[cohort],
                    label_cutoff="2024-05-04",label_settings=settings)

    def test_complete_supplied_cohort_not_approved(self):
        r=build_execution_dataset(**self.args())
        self.assertEqual(r["status"],"RESEARCH_DATASET_COMPLETE_SUPPLIED_DATES")
        self.assertEqual(r["research_label_rows"],2)
        self.assertEqual(r["approved_training_rows"],0)
        self.assertFalse(r["candidate_roster_verified"])

    def test_missing_and_unmatured_dates_reported(self):
        a=self.args()
        a["expected_signal_dates"].append("2024-05-02")
        a["label_cutoff"]="2024-05-03"
        r=build_execution_dataset(**a)
        self.assertEqual(r["date_status_counts"],{"MISSING_COHORT":1,"NOT_MATURE_AT_CUTOFF":1})
        self.assertEqual(r["rows"],[])
        self.assertEqual(r["status"],"DATASET_COVERAGE_BLOCKED")

    def test_incomplete_cohort_not_silently_replaced(self):
        a=self.args()
        a["cohorts"][0]["sessions"][1]["bars"]["2401"]["buy_eligible"]=False
        r=build_execution_dataset(**a)
        self.assertEqual(r["research_label_rows"],0)
        self.assertEqual(r["cohort_audit"][0]["candidate_status_counts"],{"CLOSED":1,"NO_ENTRY":1})
        self.assertEqual(r["date_status_counts"],{"INCOMPLETE_COHORT_BLOCKED":1})

    def test_duplicate_and_unexpected_dates_rejected(self):
        a=self.args()
        a["cohorts"].append(a["cohorts"][0])
        with self.assertRaises(ValueError):
            build_execution_dataset(**a)
        a=self.args()
        a["expected_signal_dates"]=["2024-05-02"]
        with self.assertRaises(ValueError):
            build_execution_dataset(**a)


if __name__=="__main__":
    unittest.main()
