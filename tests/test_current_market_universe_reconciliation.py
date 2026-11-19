import unittest

from scripts.reconcile_current_market_universe import reconcile_records


class CurrentMarketUniverseReconciliationTests(unittest.TestCase):
    def test_matching_sources_remain_candidate_pending_subtype(self):
        result = reconcile_records(
            [{"stock_id": "2330", "name": "台積電", "market": "TWSE", "listing_date_raw": "1994/09/05"}],
            [{"stock_id": "6488", "name": "環球晶圓", "market": "TPEX"}],
            [
                {"證券代號": "2330", "證券名稱": "台積電", "市場別": "上市", "證券狀態": "正常"},
                {"證券代號": "6488", "證券名稱": "環球晶", "市場別": "上櫃", "證券狀態": "正常"},
            ],
        )
        self.assertEqual(result["bucket_counts"]["candidate"], 2)
        self.assertEqual(result["bucket_counts"]["review"], 0)
        self.assertFalse(result["common_stock_classification_confirmed"])
        self.assertFalse(result["quote_download_authorized"])

    def test_tdcc_terminated_status_creates_review_not_silent_exclusion(self):
        result = reconcile_records(
            [{"stock_id": "1808", "name": "潤隆建設股份有限公司", "market": "TWSE", "listing_date_raw": "19941026"}],
            [],
            [{"證券代號": "1808", "證券名稱": "潤隆", "市場別": "終止上市櫃", "證券狀態": "減資/停止帳簿劃撥"}],
        )
        record = result["records"][0]
        self.assertEqual(record["bucket"], "review")
        self.assertEqual(record["review_reason"], "tdcc_status_conflicts_with_current_exchange_snapshot")
        self.assertEqual(result["bucket_counts"]["excluded"], 0)

    def test_tdcc_only_active_instruments_are_not_mislabeled_as_excluded(self):
        result = reconcile_records(
            [],
            [],
            [],
            [{"stock_id": "0050", "name": "元大台灣50", "market": "上市", "status": "正常"}],
        )
        self.assertEqual(result["tdcc_active_instruments_not_in_exchange_company_snapshots_count"], 1)
        self.assertEqual(result["bucket_counts"]["excluded"], 0)


if __name__ == "__main__":
    unittest.main()
