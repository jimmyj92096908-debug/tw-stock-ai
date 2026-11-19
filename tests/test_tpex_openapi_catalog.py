import unittest
from scripts.audit_tpex_openapi_catalog import inspect_catalog

class TpexOpenApiCatalogTests(unittest.TestCase):
    def test_discovers_etn_and_bond_routes(self):
        payload = {"openapi":"3.0.0","info":{"title":"TPEx"},
            "paths":{
                "/etn_list":{"get":{"summary":"ETN listing"}},
                "/bond_basic":{"get":{"summary":"債券基本資料"}},
                "/quote":{"get":{"summary":"Daily quote"}},
            }}
        result = inspect_catalog(payload)
        self.assertEqual(result["path_count"], 3)
        self.assertEqual({x["path"] for x in result["matching_routes"]},
                         {"/etn_list", "/bond_basic"})

    def test_rejects_missing_paths(self):
        with self.assertRaises(ValueError):
            inspect_catalog({"openapi":"3.0.0"})

if __name__ == "__main__":
    unittest.main()
