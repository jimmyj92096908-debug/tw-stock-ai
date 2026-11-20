"""Model acceptance: time separation, no data invention, deterministic rank."""
import unittest
from datetime import date
from src.factor_model_validation import evaluate_rows, EVALUATION_SQL, MODEL_VERSION


def make_row(stock, score, entry=100, exit_=105, day="2026-10-01", coverage=0.6):
    return {
        "market": "twse", "stock_id": stock, "as_of_date": date.fromisoformat(day),
        "total_score": score, "coverage_weight": coverage,
        "entry_close": entry, "exit_close": exit_,
    }


class CompositeFactorModelTests(unittest.TestCase):
    def test_tie_break_and_top_benchmark(self):
        rows = [make_row(str(i), 100-i, 100, 110 if i == 0 else 100)
                for i in range(10)]
        r = evaluate_rows(rows)
        self.assertEqual(r["model_version"], MODEL_VERSION)
        self.assertEqual(r["signal_dates"], 1)
        self.assertEqual(r["periods"][0]["selected"], 2)
        self.assertAlmostEqual(r["periods"][0]["top_mean_return"], 0.05)
        self.assertAlmostEqual(r["periods"][0]["universe_mean_return"], 0.01)
        self.assertAlmostEqual(r["periods"][0]["excess_return"], 0.04)
        self.assertFalse(r["production_validated"])

    def test_uses_next_session_entry_not_signal_close(self):
        rows = [make_row(str(i), i, 200, 210) for i in range(5)]
        rows[0]["signal_close"] = 1
        self.assertAlmostEqual(evaluate_rows(rows)["mean_top_return"], 0.05)

    def test_missing_forward_prices_do_not_count_as_wins(self):
        rows = [make_row(str(i), i) for i in range(5)]
        rows[0]["exit_close"] = None
        result = evaluate_rows(rows)
        self.assertEqual(result["signal_dates"], 0)
        self.assertEqual(result["excluded_rows"]["missing_future_price"], 1)
        self.assertIsNone(result["mean_excess_return"])

    def test_coverage_and_bad_scores_rejected(self):
        rows = [make_row("a", 90, coverage=0.3),
                make_row("b", 101), make_row("c", 60, entry=0)]
        result = evaluate_rows(rows)
        self.assertEqual(result["signal_dates"], 0)
        self.assertEqual(result["excluded_rows"]["insufficient_coverage"], 1)
        self.assertEqual(result["excluded_rows"]["invalid_or_missing"], 1)
        self.assertEqual(result["excluded_rows"]["missing_future_price"], 1)

    def test_duplicate_key_is_not_double_counted(self):
        rows = [make_row(str(i), i) for i in range(5)]
        rows.append(make_row("0", 100, 100, 1000))
        result = evaluate_rows(rows)
        self.assertEqual(result["excluded_rows"]["duplicate_key"], 1)
        self.assertEqual(result["periods"][0]["universe"], 5)

    def test_order_permutation_cannot_change_outcome(self):
        rows = [make_row(str(i), 50, exit_=100+i) for i in range(10)]
        self.assertEqual(evaluate_rows(rows), evaluate_rows(list(reversed(rows))))

    def test_multiple_dates_and_small_cohort(self):
        rows = [make_row(str(i), i) for i in range(5)]
        rows.extend(make_row(str(i), i, day="2026-10-02") for i in range(3))
        result = evaluate_rows(rows)
        self.assertEqual(result["signal_dates"], 1)
        self.assertEqual(result["skipped_small_universe_dates"], 1)

    def test_readonly_query_requires_same_date_and_forward_leads(self):
        self.assertIn("c.trade_date=s.as_of_date", EVALUATION_SQL)
        self.assertIn("LEAD(close,1)", EVALUATION_SQL)
        self.assertIn("LEAD(close,6)", EVALUATION_SQL)
        self.assertLess(EVALUATION_SQL.index("WINDOW w"), EVALUATION_SQL.index("s.as_of_date >="))
        self.assertNotIn("INSERT ", EVALUATION_SQL)
        self.assertNotIn("UPDATE ", EVALUATION_SQL)

    def test_rejects_invalid_parameters(self):
        for kwargs in ({"min_per_date":1},{"top_fraction":0},{"top_fraction":2}):
            with self.assertRaises(ValueError):
                evaluate_rows([], **kwargs)


if __name__ == "__main__":
    unittest.main()
