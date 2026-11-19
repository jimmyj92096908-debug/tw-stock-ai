import unittest

from scripts.analyze_tdcc_universe_candidates import analyze_rows


class TDCCUniverseCandidateTests(unittest.TestCase):
    def test_listed_otc_active_are_candidates_but_not_accepted(self):
        rows = [
            {"證券代號": "2330", "證券名稱": "測試", "市場別": "上市", "證券狀態": "正常"},
            {"證券代號": "6488", "證券名稱": "測試", "市場別": "上櫃", "證券狀態": "正常"},
        ]
        result = analyze_rows(rows)
        self.assertEqual(result["current_listed_otc_active_candidate_count"], 2)
        self.assertFalse(result["trading_universe_accepted"])
        self.assertFalse(result["quote_download_authorized"])

    def test_emerging_kept_separate(self):
        result = analyze_rows([
            {"證券代號": "1234", "證券名稱": "測試", "市場別": "興櫃", "證券狀態": "正常"},
        ])
        self.assertEqual(result["emerging_active_candidate_count"], 1)
        self.assertEqual(result["current_listed_otc_active_candidate_count"], 0)

    def test_inactive_and_terminated_not_current_candidates(self):
        result = analyze_rows([
            {"證券代號": "0001", "證券名稱": "測試", "市場別": "終止上市櫃", "證券狀態": "下市櫃/暫停交易"},
            {"證券代號": "1111", "證券名稱": "測試", "市場別": "上市", "證券狀態": "減資/停止帳簿劃撥"},
        ])
        self.assertEqual(result["current_listed_otc_active_candidate_count"], 0)
        self.assertEqual(result["scope_bucket_counts"]["terminated_out_of_scope"], 1)
        self.assertEqual(result["scope_bucket_counts"]["listed_candidate"], 1)

    def test_unknown_market_is_review_bucket(self):
        result = analyze_rows([
            {"證券代號": "9999", "證券名稱": "測試", "市場別": "未知", "證券狀態": "正常"},
        ])
        self.assertEqual(result["unknown_market_review_count"], 1)


if __name__ == "__main__":
    unittest.main()
