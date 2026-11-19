import json
import unittest
from pathlib import Path


class InstrumentClassificationSourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path("data/universe/instrument_classification_sources.json")
        cls.registry = json.loads(path.read_text(encoding="utf-8"))

    def test_registry_is_fail_closed(self):
        policy = self.registry["policy"]
        self.assertFalse(policy["automatic_exclusion_without_exact_security_code_match"])
        self.assertFalse(policy["common_stock_classification_confirmed"])
        self.assertFalse(policy["historical_universe_accepted"])
        self.assertFalse(policy["quote_download_authorized"])
        self.assertFalse(policy["database_modified"])
        self.assertFalse(policy["five_year_quotes_downloaded"])

    def test_required_official_categories_are_present(self):
        sources = {item["id"]: item for item in self.registry["sources"]}
        for source_id in (
            "twse_warrants",
            "twse_fund_basic",
            "tpex_warrants",
            "tpex_etf_infohub",
            "tpex_etn_product_definition",
            "tdcc_current_securities_master",
        ):
            self.assertIn(source_id, sources)
            self.assertTrue(sources[source_id]["url"].startswith("https://"))

    def test_etn_definition_alone_cannot_exclude_a_security(self):
        sources = {item["id"]: item for item in self.registry["sources"]}
        self.assertFalse(
            sources["tpex_etn_product_definition"][
                "automatic_exclusion_eligible_after_schema_validation"
            ]
        )


if __name__ == "__main__":
    unittest.main()
