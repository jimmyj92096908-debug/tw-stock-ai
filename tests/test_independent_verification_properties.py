"""Deterministic, generated properties and a separate arithmetic oracle.

This suite intentionally does NOT import implementation weight constants.
Production database, LINE, network, and broker access are not used.
"""
from __future__ import annotations

from fractions import Fraction
import random
import unittest

from src import chip_score, composite_score


# Reviewer-owned contract values: never import weights from the code under test.
CHIP_WEIGHTS = {"institutional": 40, "margin": 25, "tdcc": 25, "insider": 10}
COMPOSITE_WEIGHTS = {"technical": 35, "smc": 25, "chip": 40}


def reference_score(values, weights, minimum=50):
    """Independent exact rational oracle for generated integer factor scores."""
    present = [(weights[key], values[key]) for key in weights
               if key in values and values[key] is not None]
    weight = sum(w for w, _ in present)
    if not weight:
        return None, 0.0
    weighted = sum(Fraction(w * v, weight) for w, v in present)
    result = round(float(weighted), 2)
    result = min(100.0, max(0.0, result))
    return (result if weight >= minimum else None), weight / 100.0


def generated_cases(weights, seed=20261124, count=512):
    rng = random.Random(seed)
    for _ in range(count):
        yield {
            key: (None if rng.randrange(5) == 0 else rng.randrange(101))
            for key in weights
        }


class GeneratedArithmeticProperties(unittest.TestCase):
    def test_chip_scores_match_independent_reference(self):
        for case in generated_cases(CHIP_WEIGHTS):
            with self.subTest(case=case):
                score, coverage = chip_score.publishable_score(case)
                expected, expected_coverage = reference_score(case, CHIP_WEIGHTS)
                self.assertEqual(coverage, expected_coverage)
                if expected is None:
                    self.assertIsNone(score)
                else:
                    self.assertIsNotNone(score)
                    # Float vs rational half-cent ties may round one cent apart.
                    self.assertLessEqual(abs(score - expected), 0.011)
                    self.assertGreaterEqual(score, 0)
                    self.assertLessEqual(score, 100)

    def test_composite_scores_match_independent_reference(self):
        for case in generated_cases(COMPOSITE_WEIGHTS, seed=20261125):
            with self.subTest(case=case):
                score, coverage = composite_score.combine_scores(case)
                expected, expected_coverage = reference_score(
                    case, COMPOSITE_WEIGHTS
                )
                self.assertAlmostEqual(coverage, expected_coverage, places=10)
                if expected is None:
                    self.assertIsNone(score)
                else:
                    self.assertIsNotNone(score)
                    self.assertLessEqual(abs(score - expected), 0.011)
                    self.assertGreaterEqual(score, 0)
                    self.assertLessEqual(score, 100)

    def test_missing_is_not_zero_and_low_coverage_is_blocked(self):
        self.assertEqual(chip_score.publishable_score({}), (None, 0.0))
        self.assertEqual(chip_score.publishable_score({"insider": 0}), (None, .10))
        self.assertEqual(composite_score.combine_scores({"smc": 0}), (None, .25))
        self.assertEqual(chip_score.publishable_score(
            {"institutional": 0, "margin": 0}
        ), (0.0, .65))
        self.assertEqual(composite_score.combine_scores(
            {"technical": 0, "smc": 0}
        ), (0.0, .60))

    def test_constant_values_and_monotonicity(self):
        rng = random.Random(20261126)
        for weights, scorer in [
            (CHIP_WEIGHTS, chip_score.publishable_score),
            (COMPOSITE_WEIGHTS, composite_score.combine_scores),
        ]:
            for _ in range(250):
                x = rng.randrange(101)
                same = {key: x for key in weights}
                value, coverage = scorer(same)
                self.assertEqual((value, coverage), (float(x), 1.0))
                key = rng.choice(list(weights))
                increased = dict(same)
                increased[key] = min(100, x + rng.randrange(1, 30))
                higher, higher_coverage = scorer(increased)
                self.assertEqual(higher_coverage, coverage)
                self.assertGreaterEqual(higher, value)

    def test_unrecognized_extra_keys_do_not_change_scores(self):
        rng = random.Random(20261127)
        for weights, scorer in [
            (CHIP_WEIGHTS, chip_score.publishable_score),
            (COMPOSITE_WEIGHTS, composite_score.combine_scores),
        ]:
            for case in generated_cases(weights, count=100):
                extra = dict(case)
                extra["__unknown_future_factor"] = rng.randrange(101)
                self.assertEqual(scorer(case), scorer(extra))


if __name__ == "__main__":
    unittest.main()
