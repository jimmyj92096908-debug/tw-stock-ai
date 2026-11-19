import unittest
from scripts.audit_tpex_bond_sources import ROUTES, inspect_rows

class TpexBondSourceAuditTests(unittest.TestCase):
    def test_routes_have_exact_bond_code_field(self):
        self.assertGreaterEqual(len(ROUTES), 10)
        self.assertTrue(all(field == "BondCode" for _, field in ROUTES.values()))

    def test_extracts_exact_bond_codes(self):
        self.assertEqual(inspect_rows([{"BondCode": "A123"}, {"BondCode": "B456"}], "BondCode"),
                         ["A123", "B456"])

    def test_rejects_empty_payload(self):
        with self.assertRaises(ValueError):
            inspect_rows([], "BondCode")

    def test_rejects_missing_code(self):
        with self.assertRaises(ValueError):
            inspect_rows([{"ShortName": "test"}], "BondCode")

    def test_rejects_duplicate_codes(self):
        with self.assertRaises(ValueError):
            inspect_rows([{"BondCode": "A123"}, {"BondCode": "A123"}], "BondCode")

    def test_rejects_non_object_rows(self):
        with self.assertRaises(ValueError):
            inspect_rows(["A123"], "BondCode")

if __name__ == "__main__":
    unittest.main()
