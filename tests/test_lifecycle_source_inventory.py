import json
import unittest
from pathlib import Path

INVENTORY = Path("data/universe/historical_lifecycle_sources.json")

class LifecycleSourceInventoryTests(unittest.TestCase):
    def test_twse_terminated_endpoint_has_observed_schema_and_dates(self):
        inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        source = next(s for s in inventory["sources"] if s["source_id"] == "twse_terminated_listings")
        self.assertEqual(source["status"], "live_response_schema_and_coverage_observed")
        self.assertEqual(source["observed_schema"], ["DelistingDate", "Company", "Code"])
        self.assertEqual(source["date_format"], "ROC YYYY/MM/DD")
        self.assertEqual(source["observed_date_range"]["earliest"], "090/01/20")
        self.assertEqual(source["observed_date_range"]["latest"], "115/11/18")

    def test_tpex_source_remains_unverified_for_bulk_automation(self):
        inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        source = next(s for s in inventory["sources"] if s["source_id"] == "tpex_delisted_company_query")
        self.assertIn("unverified", source["status"])
        self.assertFalse(inventory["accepted_historical_universe"])
        self.assertFalse(inventory["download_authorized"])

if __name__ == "__main__":
    unittest.main()
