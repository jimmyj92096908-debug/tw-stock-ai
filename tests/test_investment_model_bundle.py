"""Contracts for the unified research bundle; no DB or LINE integration needed."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from src import investment_model_bundle as bundle
from scripts import investment_model_pipeline as runner

ROOT = Path(__file__).resolve().parents[1]
MODEL = json.loads((ROOT/"models/tw-factor-ridge-1-research.json").read_text())
EVALUATION = json.loads((ROOT/"models/tw-factor-ridge-1-evaluation.json").read_text())


def stock_dates(**kwargs):
    row = {
        "latest_price_date": date(2026,11,20),
        "latest_technical_date": date(2026,11,19),
        "latest_composite_date": date(2026,11,19),
        "latest_composite_score": 62.12,
        "composite_chip_component": None,
        "latest_publishable_chip_date": date(2026,11,20),
        "latest_publishable_chip_score": 40.65,
        "latest_publishable_chip_coverage": .65,
    }
    row.update(kwargs)
    return row


def ranking_row(i, *, score_date="2026-11-19"):
    return {
        "market":"twse", "stock_id":str(1300+i),
        "stock_name":f"fixture_{i}",
        "as_of_date":date.fromisoformat(score_date),
        "total_score":85-i,"technical_score":75-i,
        "smc_score":70+i,"short_term_score":80-i,
        "swing_score":72+i,"long_term_score":None,
        "coverage_weight":.60,"signal_close":100+i,
    }


class InvestmentBundleTests(unittest.TestCase):
    def test_existing_saved_artifacts_are_not_misrepresented_as_profitable(self):
        audit = bundle.verify_fitted_model(MODEL, EVALUATION)
        self.assertEqual(audit["model_version"], "tw-factor-ridge-1")
        self.assertEqual(audit["research_evidence_status"],"INCOMPLETE_OR_FAILED")
        self.assertIn("holdout_not_pristine",audit["research_evidence_problems"])
        self.assertIn("no_development_row_fingerprint",audit["research_evidence_problems"])
        self.assertIn("non_positive_holdout_net_excess",audit["research_evidence_problems"])
        self.assertAlmostEqual(audit["holdout_net_excess"],-.02114523)
        self.assertEqual(audit["holdout_dates"],21)
        self.assertFalse(audit["live_trading_approved"])
        self.assertFalse(audit["line_signal_delivery_approved"])

    def test_2330_independent_chip_is_not_retroactively_included(self):
        assessed = bundle.stock_date_assessment(stock_dates())
        self.assertEqual(assessed["price_date"],"2026-11-20")
        self.assertEqual(assessed["technical_date"],"2026-11-19")
        self.assertEqual(assessed["composite_date"],"2026-11-19")
        self.assertEqual(assessed["independent_chip_score"],40.65)
        self.assertEqual(assessed["independent_chip_coverage"],.65)
        self.assertTrue(assessed["new_chip_not_in_older_composite"])
        self.assertFalse(assessed["composite_matches_latest_price"])
        self.assertFalse(assessed["model_data_ready_for_current_ranking"])
        self.assertIsNone(assessed["composite_chip_component"])

    def test_publishable_chip_staleness_future_and_low_coverage_fail_closed(self):
        cases = [
            {"latest_publishable_chip_date":date(2026,11,21)},
            {"latest_publishable_chip_date":date(2026,11,12)},
            {"latest_publishable_chip_coverage":.49},
            {"latest_publishable_chip_score":None},
            {"latest_publishable_chip_score":float("nan")},
            {"latest_publishable_chip_score":101},
        ]
        for case in cases:
            with self.subTest(case=case):
                data=bundle.stock_date_assessment(stock_dates(**case))
                self.assertFalse(data["independent_chip_is_current"])
                self.assertIsNone(data["independent_chip_score"])
        boundary=bundle.stock_date_assessment(
            stock_dates(latest_publishable_chip_date=date(2026,11,13))
        )
        self.assertTrue(boundary["independent_chip_is_current"])
        self.assertEqual(boundary["chip_age_calendar_days"],7)

    def test_schema_tampering_never_yields_model_ranking(self):
        result=bundle.assemble_research_bundle(
            {**MODEL,"weights":[1,2]},EVALUATION,[ranking_row(0)],stock_dates()
        )
        self.assertEqual(result["ranking"]["stocks"],[])
        self.assertEqual(result["ranking"]["reason"],"invalid_fitted_model")
        self.assertTrue(result["abstain_from_trading"])
        self.assertFalse(result["orders_enabled"])
        self.assertFalse(result["publish_line_trade_signal"])

    def test_assembled_historical_rank_remains_research_only(self):
        result=bundle.assemble_research_bundle(
            MODEL,EVALUATION,[ranking_row(i) for i in range(10)],stock_dates(),
            limit=3
        )
        self.assertEqual(len(result["ranking"]["stocks"]),3)
        self.assertEqual(result["ranking"]["date"],"2026-11-19")
        self.assertFalse(result["ranking_matches_reference_price_date"])
        self.assertEqual(result["overall_status"],"RESEARCH_ONLY_EVIDENCE_BLOCKED")
        self.assertTrue(result["abstain_from_trading"])
        self.assertFalse(result["publish_line_trade_signal"])
        self.assertFalse(result["orders_enabled"])
        self.assertFalse(result["production_database_modified"])

    def test_cross_date_rank_input_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"Cannot mix score dates"):
            bundle.assemble_research_bundle(
                MODEL,EVALUATION,
                [ranking_row(0,score_date="2026-11-19"),
                 ranking_row(1,score_date="2026-11-20")],
                stock_dates()
            )

    def test_query_contract_only_reads_public_research_and_exact_symbol(self):
        sql=bundle.STOCK_STATUS_SQL
        self.assertEqual(sql.count("%s"),16)
        for table in ("daily_prices","daily_technicals",
                      "daily_composite_scores","daily_chip_scores"):
            self.assertIn("public."+table,sql)
        self.assertNotIn("line_messages",sql)
        self.assertNotIn("INSERT INTO",sql)
        self.assertNotIn("UPDATE ",sql)
        self.assertIn("coverage_weight >= 0.50",sql)

    def test_default_offline_loads_committed_model_without_db(self):
        with patch.object(runner, "query_same_snapshot",
                          side_effect=AssertionError("No Neon in offline mode")):
            out=runner.make_bundle()
        self.assertEqual(out["data_mode"],"offline_committed_evidence_only")
        self.assertTrue(out["offline_stock_data_is_not_live"])
        self.assertIsNone(out["stock_data"]["price_date"])
        self.assertTrue(out["abstain_from_trading"])

    def test_live_requires_explicit_opt_in_and_bounded_stock_parameters(self):
        with self.assertRaisesRegex(ValueError,"INVESTMENT_MODEL_READONLY"):
            runner.make_bundle(live=True)
        for market,stock in (("other","2330"),("twse","23 0"),("twse","１３００")):
            with self.subTest(market=market,stock=stock):
                with self.assertRaises(ValueError):
                    runner.make_bundle(market=market,stock_id=stock)
        with self.assertRaises(ValueError):
            runner.make_bundle(limit=0)

    def test_live_bundle_ranks_existing_data_without_writing(self):
        with patch.dict("os.environ",{"INVESTMENT_MODEL_READONLY":"yes"}),\
             patch.object(runner,"query_same_snapshot",return_value=(
                 [ranking_row(i) for i in range(10)],stock_dates()
             )) as query:
            out=runner.make_bundle(
                live=True,database_url="mock-only",market="twse",stock_id="2330"
            )
        query.assert_called_once_with("mock-only","twse","2330")
        self.assertEqual(out["stock_data"]["independent_chip_score"],40.65)
        self.assertEqual(out["data_mode"],"existing_neon_snapshot_read_only")
        self.assertTrue(out["abstain_from_trading"])

    def test_db_queries_share_one_repeatable_read_transaction(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=conn.transaction.return_value.__enter__.return_value
        result=conn.cursor.return_value.__enter__.return_value
        result.fetchall.side_effect=[
            [ranking_row(i) for i in range(5)], [stock_dates()]
        ]
        with patch.object(runner.psycopg,"connect",return_value=conn) as connect:
            x,y=runner.query_same_snapshot("postgresql://mock","twse","2330")
        self.assertEqual(len(x),5)
        self.assertEqual(y["latest_publishable_chip_score"],40.65)
        self.assertEqual(connect.call_args.kwargs["options"],
                         "-c default_transaction_read_only=on")
        self.assertEqual(result.execute.call_args_list[0].args[0],
                         "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        self.assertEqual(result.execute.call_args_list[3].args[1],
                         ("twse","2330")*8)

    def test_produces_local_valid_json_not_a_trading_report(self):
        with TemporaryDirectory() as folder:
            file=Path(folder)/"research.json"
            out=runner.make_bundle()
            with file.open("w",encoding="utf-8") as handle:
                runner.json.dump(out,handle,ensure_ascii=False,allow_nan=False)
            record=json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual(record["overall_status"],
                             "RESEARCH_ONLY_EVIDENCE_BLOCKED")


if __name__=="__main__":
    unittest.main()
