import csv
import tempfile
import unittest
from pathlib import Path

from scripts.reconcile_exact_instrument_exclusions import (
    load_tpex_etn_table_codes,
    reconcile_exact_codes,
    write_audit_csv,
)


class ExactInstrumentExclusionTests(unittest.TestCase):
    def test_only_exact_code_matches_are_excluded(self):
        rows = [
            {"stock_id": "0050", "name": "ETF", "market": "TWSE"},
            {"stock_id": "2330", "name": "TSMC", "market": "TWSE"},
            {"stock_id": "00411A", "name": "ETF", "market": "TPEX"},
        ]
        sources = {
            "twse_fund_basic": {"market": "TWSE", "category": "fund_or_etf", "codes": {"0050"}},
            "tpex_etf": {"market": "TPEX", "category": "etf", "codes": {"00411A"}},
        }
        result = reconcile_exact_codes(rows, sources)
        self.assertEqual(result["bucket_counts"], {"candidate": 1, "excluded": 2})
        self.assertEqual(result["records"][0]["exclusion_evidence"][0]["source_id"], "twse_fund_basic")
        self.assertEqual(result["records"][2]["exclusion_evidence"][0]["source_id"], "tpex_etf")
        self.assertFalse(result["common_stock_classification_confirmed"])

    def test_no_code_or_name_heuristics(self):
        rows = [{"stock_id": "2330", "name": "主動式基金名稱", "market": "TWSE"}]
        sources = {
            "tpex_etf": {"market": "TPEX", "category": "etf", "codes": {"00999"}}
        }
        result = reconcile_exact_codes(rows, sources)
        self.assertEqual(result["bucket_counts"], {"candidate": 1, "excluded": 0})

    def test_manual_exclusion_is_preserved_even_without_source_code_match(self):
        rows = [{"stock_id": "2330", "name": "TSMC", "market": "TWSE"}]
        manual = [{"stock_id": "1808", "name": "潤隆建設", "market": "TWSE",
                   "review_reason": "user_directed_exclusion"}]
        result = reconcile_exact_codes(rows, {}, manual)
        self.assertEqual(result["bucket_counts"], {"candidate": 1, "excluded": 1})
        self.assertEqual(result["records"][1]["stock_id"], "1808")
        self.assertEqual(result["records"][1]["bucket"], "excluded")
        self.assertEqual(result["records"][1]["manual_exclusion_reason"], "user_directed_exclusion")


    def test_csv_preserves_manual_exclusion_reason(self):
        rows = [{
            "stock_id": "1808",
            "name": "潤隆建設",
            "market": "TWSE",
            "bucket": "excluded",
            "instrument_subtype_confirmed": False,
            "exclusion_evidence": [],
            "manual_exclusion_reason": "user_directed_exclusion",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "audit.csv"
            write_audit_csv(rows, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                saved = next(csv.DictReader(handle))
        self.assertEqual(saved["stock_id"], "1808")
        self.assertEqual(saved["bucket"], "excluded")
        self.assertEqual(saved["manual_exclusion_reason"], "user_directed_exclusion")

    def test_loads_exact_etn_code_column_from_official_nested_table(self):
        payload = {
            "tables": [{
                "fields": ["證券代號", "ETN簡稱", "發行人"],
                "data": [
                    ["020041", "兆豐半導體氣候N", "發行人甲"],
                    ["020042", "測試ETN", "發行人乙"],
                ],
            }]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "etn.json"
            import json
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(load_tpex_etn_table_codes(path, "證券代號"), {"020041", "020042"})

    def test_etn_table_rejects_ambiguous_or_malformed_columns(self):
        import json
        cases = [
            {"tables": [{"fields": ["證券代號", "證券代號"], "data": [["020041", "020041"]]}]},
            {"tables": [{"fields": ["證券代號", "ETN簡稱"], "data": [["020041"]]}]},
            {"tables": [{"fields": ["ETN簡稱"], "data": [["測試"]]}]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for index, payload in enumerate(cases):
                path = Path(tmp) / f"bad-{index}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                with self.subTest(index=index), self.assertRaises(ValueError):
                    load_tpex_etn_table_codes(path, "證券代號")

    def test_duplicate_exchange_codes_rejected(self):
        rows = [
            {"stock_id": "2330", "name": "A", "market": "TWSE"},
            {"stock_id": "2330", "name": "B", "market": "TWSE"},
        ]
        with self.assertRaises(ValueError):
            reconcile_exact_codes(rows, {})


if __name__ == "__main__":
    unittest.main()
