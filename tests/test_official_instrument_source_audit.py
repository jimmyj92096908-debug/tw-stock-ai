import unittest

from scripts.audit_official_instrument_sources import inspect_payload


class OfficialInstrumentSourceAuditTests(unittest.TestCase):
    def test_recognizes_one_exact_code_field(self):
        result = inspect_payload([
            {"權證代號": "123456", "權證名稱": "測試權證"},
            {"權證代號": "234567", "權證名稱": "另一測試權證"},
        ])
        self.assertTrue(result["schema_validated"])
        self.assertEqual(result["security_code_field"], "權證代號")
        self.assertEqual(result["security_codes"], ["123456", "234567"])

    def test_recognizes_twse_fund_code_field(self):
        result = inspect_payload([{"基金代號": "0050", "基金類型": "國內成分證券指數股票型基金"}])
        self.assertTrue(result["schema_validated"])
        self.assertEqual(result["security_code_field"], "基金代號")
        self.assertEqual(result["security_codes"], ["0050"])

    def test_rejects_ambiguous_code_fields(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            inspect_payload([{"證券代號": "0050", "權證代號": "123456"}])

    def test_rejects_missing_codes(self):
        with self.assertRaisesRegex(ValueError, "Missing security codes"):
            inspect_payload([{"證券代號": "0050"}, {"證券代號": ""}])

    def test_rejects_duplicate_codes(self):
        with self.assertRaisesRegex(ValueError, "Duplicate security code"):
            inspect_payload([{"證券代號": "0050"}, {"證券代號": "0050"}])

    def test_rejects_non_array_payload(self):
        with self.assertRaisesRegex(ValueError, "non-empty JSON array"):
            inspect_payload({"data": []})


if __name__ == "__main__":
    unittest.main()
