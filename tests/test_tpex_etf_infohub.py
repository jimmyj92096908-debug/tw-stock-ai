import unittest

from scripts.audit_tpex_etf_infohub import describe_payload


class TpexEtfInfohubTests(unittest.TestCase):
    def test_list_payload(self):
        result = describe_payload([{"證券代號": "00999", "ETF名稱": "測試ETF"}])
        self.assertTrue(result["schema_validated"])
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["security_code_field_candidates"], ["證券代號"])
        self.assertEqual(result["security_code_field"], "證券代號")
        self.assertTrue(result["exact_security_code_field_confirmed"])

    def test_nested_payload(self):
        result = describe_payload({"data": [{"code": "00999"}]})
        self.assertEqual(result["records_container_key"], "data")
        self.assertTrue(result["schema_validated"])

    def test_prefers_etf_data_over_factor_metadata(self):
        result = describe_payload({
            "factorList": [{"factorId": "1", "factor": "ESG"}],
            "data": [{"stockNo": "00411A", "stockName": "ETF甲"},
                     {"stockNo": "006201", "stockName": "ETF乙"}],
        })
        self.assertEqual(result["records_container_key"], "data")
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["security_code_field"], "stockNo")
        self.assertEqual(result["security_code_count"], 2)
        self.assertEqual(result["security_codes"], ["00411A", "006201"])
        self.assertTrue(result["exact_security_code_field_confirmed"])

    def test_duplicate_codes_do_not_confirm_exact_list(self):
        result = describe_payload({"data": [{"stockNo": "00999"}, {"stockNo": "00999"}]})
        self.assertEqual(result["duplicate_security_code_count"], 1)
        self.assertFalse(result["exact_security_code_field_confirmed"])

    def test_unrecognized_payload_stays_unvalidated(self):
        result = describe_payload({"message": "not data"})
        self.assertFalse(result["schema_validated"])
        self.assertEqual(result["record_count"], 0)


if __name__ == "__main__":
    unittest.main()
