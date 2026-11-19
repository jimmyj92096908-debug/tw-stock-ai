import unittest
from scripts.normalize_security_lifecycle_candidates import normalize_rows, normalize_date

class LifecycleCandidateTests(unittest.TestCase):
    def test_gregorian_and_roc_dates(self):
        self.assertEqual(normalize_date("2020/05/06"), "2020-05-06")
        self.assertEqual(normalize_date("109/05/06"), "2020-05-06")
        self.assertIsNone(normalize_date("2020-99-99"))

    def test_listing_delisting_creates_unaccepted_interval(self):
        result = normalize_rows([{"公司代號":"1234","公司名稱":"範例","上市日期":"2020/01/02","終止上市日期":"2024/03/04"}], "TWSE", "official csv")
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["candidate_intervals"][0]["effective_from_candidate"], "2020-01-02")
        self.assertEqual(result["candidate_intervals"][0]["effective_to_candidate"], "2024-03-04")
        self.assertFalse(result["historical_universe_accepted"])
        self.assertFalse(result["download_authorized"])

    def test_roc_termination_date(self):
        result = normalize_rows([{"上市編號":"4321","公司名稱":"測試","終止上市日期":"112/07/08"}], "TWSE", "dataset")
        self.assertEqual(result["events"][0]["event_date"], "2023-07-08")

    def test_missing_code_and_bad_dates_are_flagged(self):
        result = normalize_rows([{"公司名稱":"缺代號","上市日期":"2020/01/01"},{"公司代號":"9999","上市日期":"bad","終止上市日期":"2020/02/30"}], "TPEX", "file")
        self.assertEqual(len(result["rejected_rows"]), 3)
        self.assertEqual(result["event_count"], 0)

    def test_delisting_before_listing_rejected_interval(self):
        result = normalize_rows([{"公司代號":"0002","上市日期":"2022/01/01","終止上市日期":"2021/01/01"}], "TWSE", "source")
        self.assertEqual(result["candidate_interval_count"], 0)
        self.assertTrue(any(r["reason"]=="delisting_before_listing" for r in result["rejected_rows"]))

if __name__ == "__main__":
    unittest.main()
