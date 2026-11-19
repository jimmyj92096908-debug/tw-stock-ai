import tempfile
import unittest
from pathlib import Path

from scripts.parse_tpex_calendar_candidates import (
    classify_context,
    extract_candidates,
    parse_directory,
)


class TpexCalendarCandidateTests(unittest.TestCase):
    def test_chinese_dates_are_candidates_not_accepted_closures(self):
        text = "農曆春節前股票交易系統最後交易日\n1 月 17 日 二\n1 月 18 日及 1 月 19 日市場無交易"
        rows = extract_candidates(text, 112, "abc")
        self.assertEqual([row["date"] for row in rows], ["2023-01-17", "2023-01-18", "2023-01-19"])
        self.assertTrue(all(row["occurrences"][0]["calendar_status"] == "candidate_only_not_accepted" for row in rows))
        self.assertEqual(rows[0]["occurrences"][0]["scope_classification"], "explicit_equity_scope_candidate")

    def test_bond_context_is_not_classified_as_equity(self):
        self.assertEqual(classify_context("國際債券交易系統最後交易日"), "bond_or_non_equity_scope_review")

    def test_english_dates_are_extracted(self):
        rows = extract_candidates("February\n5 (Friday)\nLast Trading Day before holiday (Listed Stock)", 110, "xyz")
        self.assertEqual(rows[0]["date"], "2021-02-05")
        self.assertEqual(rows[0]["occurrences"][0]["scope_classification"], "explicit_equity_scope_candidate")

    def test_escaped_newline_english_calendar_text_is_normalized(self):
        text = "February\\n5 (Friday)\\nLast Trading Day before holiday (Listed Stock)"
        rows = extract_candidates(text, 110, "xyz")
        self.assertEqual(rows[0]["date"], "2021-02-05")
        self.assertEqual(rows[0]["occurrences"][0]["scope_classification"], "explicit_equity_scope_candidate")

    def test_directory_output_never_accepts_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "112.txt").write_text("1 月 1 日", encoding="utf-8")
            result = parse_directory(Path(tmp))
        self.assertFalse(result["calendar_days_accepted"])
        self.assertFalse(result["trading_sessions_generated"])
        self.assertEqual(result["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
