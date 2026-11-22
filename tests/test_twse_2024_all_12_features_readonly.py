"""Full cohort technical/SMC no future parity, all stock factors in RAM."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import twse_2024_all_12_features_readonly as m
from tests.test_twse_2024_full_market_ma240_readonly import five_stock_mock


class FullTwelveFactorReadOnlyTests(TestCase):
    def test_all_five_synthetic_stocks_have_full_12_causal_checks(self):
        report = m.audit_complete_12_feature_cohort(iter(five_stock_mock()), minimum=5)
        self.assertEqual(report["eligible_current_listed_stocks"], 5)
        self.assertEqual(report["genuine_2024_market_days"], 242)
        self.assertEqual(report["official_source_rows_evaluated"], 5*242)
        self.assertEqual(report["exact_ma240_no_future_checks"], 5)
        self.assertEqual(report["complete_12_technical_smc_feature_vectors"], 5)
        self.assertEqual(report["full_12_feature_prior_day_no_future_parity_checks"], 5)
        self.assertEqual(report["raw_factor_count"], 12)
        self.assertEqual(len(report["only_aggregate_source_factor_sha256"]), 64)
        self.assertFalse(report["corporate_actions_adjusted"])
        self.assertFalse(report["independent_forward_cost_stressed_alpha_positive"])
        self.assertFalse(report["live_trading_approved"])
        self.assertEqual(report["neon_price_factor_model_rows_written"], 0)
        self.assertEqual(report["public_per_stock_source_or_vector_artifacts"], 0)
        self.assertNotIn("stock_id", report)
        self.assertNotIn("feature_vector", report)

    def test_incomplete_stock_bad_price_and_sorted_requirement(self):
        for case in ("gap", "duplicate", "price", "volume", "source",
                     "ticker", "wrong_day", "reverse"):
            rows = five_stock_mock()
            if case == "gap":
                del rows[10]
            elif case == "duplicate":
                rows[10] = dict(rows[9])
            elif case == "price":
                rows[10]["close"] = Decimal("-1")
            elif case == "volume":
                rows[10]["volume"] = 100.5
            elif case == "source":
                rows[10]["source"] = "OTHER"
            elif case == "ticker":
                rows[10]["stock_id"] = "1589"
            elif case == "wrong_day":
                rows[10]["trade_date"] = date(2022,2,2)
            elif case == "reverse":
                rows[0], rows[243] = rows[243], rows[0]
            with self.subTest(case=case), self.assertRaises(ValueError):
                m.audit_complete_12_feature_cohort(rows, minimum=5)

    def test_single_pg_source_query_with_readonly_transaction(self):
        rows=five_stock_mock()
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=MagicMock()
        cur.__enter__.return_value=cur
        cur.fetchmany.side_effect=[rows[:500],rows[500:],[]]
        conn.cursor.return_value=cur
        audit=m.audit_complete_12_feature_cohort
        with (
            TemporaryDirectory() as td,
            patch("psycopg.connect",return_value=conn) as dial,
            patch.object(m,"audit_complete_12_feature_cohort",
                         side_effect=lambda iterable:audit(iterable,minimum=5)),
        ):
            path=Path(td)/"aggregates.json"
            report=m.run("postgresql://synthetic",output=path)
            self.assertEqual(json.loads(path.read_text()),report)
            self.assertNotIn('"stock_id"',path.read_text())
            self.assertNotIn('"feature_vector"',path.read_text())
            self.assertIn("default_transaction_read_only=on",
                          dial.call_args.kwargs["options"])
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                         "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute.assert_called_once_with(
                m.STREAM_SQL,
                (m.YEAR_START,m.YEAR_END,m.YEAR_START,m.YEAR_END)
            )

    def test_defaults_are_real_800plus_and_no_dml(self):
        with self.assertRaises(ValueError):
            m.audit_complete_12_feature_cohort(five_stock_mock())
        self.assertEqual(m.MIN_FULL_STOCKS,800)
        self.assertEqual(m.MAX_TOTAL_ROWS,250000)
        self.assertIn("official_current_listed",m.STREAM_SQL)
        self.assertIn("model_stock_exclusions",m.STREAM_SQL)
        self.assertIn("p.stock_id<>'1589'",m.STREAM_SQL)
        for mutation in ("INSERT INTO","UPDATE ","DELETE FROM","DROP ","TRUNCATE "):
            self.assertNotIn(mutation,m.STREAM_SQL.upper())
