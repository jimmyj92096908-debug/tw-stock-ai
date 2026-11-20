import unittest
from src.chip_score import clamp, weighted_score, publishable_score, parse_stock_ids


class ChipScoreTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(-5), 0)
        self.assertEqual(clamp(120), 100)

    def test_missing_components_are_not_zero(self):
        score, coverage = weighted_score({
            "institutional": 80, "margin": None, "tdcc": 60, "insider": None
        })
        self.assertEqual(score, 72.31)
        self.assertEqual(coverage, 0.65)

    def test_no_available_components(self):
        self.assertEqual(weighted_score({
            "institutional": None, "margin": None, "tdcc": None, "insider": None
        }), (None, 0.0))

    def test_overall_score_requires_minimum_coverage(self):
        score, coverage = publishable_score({
            "institutional": None, "margin": None, "tdcc": None, "insider": 100
        })
        self.assertIsNone(score)
        self.assertEqual(coverage, 0.10)

    def test_overall_score_with_sufficient_coverage(self):
        score, coverage = publishable_score({
            "institutional": 80, "margin": None, "tdcc": 60, "insider": None
        })
        self.assertEqual(score, 72.31)
        self.assertEqual(coverage, 0.65)

    def test_bound_tracked_stock_ids_for_daily_scoring(self):
        self.assertEqual(parse_stock_ids("2330,6213,4919,7827,8937"),
                         frozenset({"2330", "6213", "4919", "7827", "8937"}))
        for bad in ("", "2330,,6213", "2330,2330", "2330;DROP TABLE", "ABC", "1",
                    ",".join(str(1000+i) for i in range(41))):
            with self.assertRaises(ValueError):
                parse_stock_ids(bad)

    def test_scoped_query_uses_parameterized_stock_ids(self):
        from unittest.mock import MagicMock, patch
        from src.chip_score import calculate_all

        conn = MagicMock()
        cursor = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        with patch("src.chip_score.psycopg.connect", return_value=conn):
            self.assertEqual(calculate_all("postgresql://example.invalid/db",
                                           parse_stock_ids("2330,6213")), 0)
        query, params = cursor.execute.call_args.args
        self.assertIn("stock_id = ANY(%s)", query)
        self.assertEqual(params, (["2330", "6213"],))
        self.assertNotIn("2330", query)

    def test_full_coverage(self):
        score, coverage = weighted_score({
            "institutional": 50, "margin": 50, "tdcc": 50, "insider": 50
        })
        self.assertEqual(score, 50)
        self.assertEqual(coverage, 1.0)


if __name__ == "__main__":
    unittest.main()
