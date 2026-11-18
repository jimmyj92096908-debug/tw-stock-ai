import unittest
from src.chip_score import clamp, weighted_score


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

    def test_full_coverage(self):
        score, coverage = weighted_score({
            "institutional": 50, "margin": 50, "tdcc": 50, "insider": 50
        })
        self.assertEqual(score, 50)
        self.assertEqual(coverage, 1.0)


if __name__ == "__main__":
    unittest.main()
