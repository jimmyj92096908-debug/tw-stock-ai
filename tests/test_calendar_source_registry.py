import json
import unittest
from pathlib import Path


class CalendarSourceRegistryTests(unittest.TestCase):
    def test_registry_covers_required_years_for_both_markets(self):
        registry_path = Path(__file__).resolve().parents[1] / "data" / "calendars" / "source_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        expected = {str(year) for year in range(110, 116)}
        for market in ("twse", "tpex"):
            with self.subTest(market=market):
                self.assertEqual(set(registry["markets"][market]), expected)
                for year, item in registry["markets"][market].items():
                    self.assertTrue(item["url"].startswith("https://"))
                    self.assertTrue(item["status"])
                    self.assertTrue(item["description"])
                    self.assertIn(year, expected)

    def test_registry_does_not_claim_unparsed_sources_are_validated(self):
        registry_path = Path(__file__).resolve().parents[1] / "data" / "calendars" / "source_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual(registry["policy"]["parse_status_for_all_entries"], "discovered_not_parsed")
        for market in ("twse", "tpex"):
            for item in registry["markets"][market].values():
                self.assertNotIn("validated", item["status"])
                self.assertNotIn("parsed", item["status"])


if __name__ == "__main__":
    unittest.main()
