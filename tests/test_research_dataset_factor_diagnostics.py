"""Fail-closed tests for historical research export and exploratory factor IC."""
from __future__ import annotations

from datetime import date,timedelta
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock,patch

from src.research_dataset import build_research_dataset,verify_dataset
from src.research_factor_diagnostics import factor_diagnostics,spearman_ic
from scripts import research_dataset_pipeline as cli


def sample(n_dates=22,n_stocks=10):
    first=date(2026,8,1)
    rows=[]
    for d in range(n_dates):
        signal=first+timedelta(days=d)
        for j in range(n_stocks):
            future=(4.5-j)/100
            rows.append({
                "market":"twse", "stock_id":str(1300+j),
                "as_of_date":signal.isoformat(),
                "total_score":90-5*j, "technical_score":90-5*j,
                "smc_score":10+8*j, "short_term_score":90-5*j,
                "swing_score":50, "long_term_score":None if j>=5 else 70-2*j,
                "coverage_weight":.60, "adjusted_close":100.0,
                "entry_date":(signal+timedelta(days=1)).isoformat(),
                "entry_close":100.0,
                "exit_date":(signal+timedelta(days=5)).isoformat(),
                "exit_close":100*(1+future),
            })
    return rows


def prepared(rows=None,*,cutoff="2026-10-31"):
    return build_research_dataset(sample() if rows is None else rows,
                                  start="2026-08-01",end="2026-08-22",
                                  label_cutoff=cutoff)


class DatasetTests(unittest.TestCase):
    def test_normalized_sorted_complete_and_reproducible(self):
        original=sample()
        one=prepared(original)
        other=prepared(list(reversed(original)))
        self.assertEqual(one,other)
        m=one["manifest"]
        self.assertEqual(m["included_rows"],220)
        self.assertEqual(m["included_dates"],22)
        self.assertEqual(m["raw_scored_dates"],22)
        self.assertEqual(len(m["rows_sha256"]),64)
        self.assertEqual(verify_dataset(one),one["rows"])
        self.assertFalse(m["sample_selection_and_survivorship_bias_audited"])
        self.assertFalse(m["pristine_future_holdout_proven"])
        self.assertFalse(m["orders_enabled"])

    def test_missing_adjusted_price_excludes_whole_day_not_single_stock(self):
        rows=sample()
        rows[0]["adjusted_close"]=None
        out=prepared(rows)
        self.assertEqual(out["manifest"]["included_dates"],21)
        self.assertEqual(out["manifest"]["included_rows"],210)
        self.assertEqual(out["manifest"]["excluded_dates_by_reason"],
                         {"incomplete_or_unmatured_forward_labels":1})
        self.assertNotIn("2026-08-01",{r["as_of_date"] for r in out["rows"]})

    def test_missing_mature_label_and_unequal_horizons_exclude_whole_day(self):
        immature=prepared(cutoff="2026-08-22")
        self.assertEqual(immature["manifest"]["included_dates"],17)
        self.assertEqual(immature["manifest"]["excluded_dates_by_reason"]
                         ["incomplete_or_unmatured_forward_labels"],5)
        rows=sample()
        rows[0]["exit_date"]="2026-08-07"
        unequal=prepared(rows)
        self.assertEqual(unequal["manifest"]["included_dates"],21)
        self.assertEqual(unequal["manifest"]["excluded_dates_by_reason"]
                         ["unmatched_holding_windows"],1)

    def test_short_or_duplicate_cohort_rejected(self):
        rows=sample(n_dates=1,n_stocks=4)
        out=build_research_dataset(rows,start="2026-08-01",end="2026-08-01",
                                   label_cutoff="2026-08-10")
        self.assertEqual(out["manifest"]["included_rows"],0)
        self.assertEqual(out["manifest"]["excluded_dates_by_reason"]
                         ["insufficient_scored_universe"],1)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            prepared(sample()+[sample()[0]])

    def test_invalid_coverage_invalid_factor_and_invalid_stock_fail_closed(self):
        for mutate in (
            {"coverage_weight":.49},
            {"technical_score":101},
            {"total_score":float("nan")},
            {"stock_id":"1808"},
            {"market":"UNKNOWN"},
            {"entry_date":"2026-01-01"},
        ):
            rows=sample()
            rows[0].update(mutate)
            if mutate=={"entry_date":"2026-01-01"}:
                self.assertEqual(prepared(rows)["manifest"]["included_dates"],21)
            else:
                with self.assertRaises(ValueError):
                    prepared(rows)

    def test_bounds_and_manifest_tampering_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"bounded"):
            build_research_dataset(sample(),start="2026-08-01",
                                   end="2026-08-22",label_cutoff="2026-10-31",
                                   max_rows=100)
        with self.assertRaisesRegex(ValueError,"start <= end"):
            build_research_dataset([],start="2026-11-01",end="2026-11-10",
                                   label_cutoff="2026-11-05")
        data=prepared()
        data["rows"][0]["exit_close"]+=10
        with self.assertRaisesRegex(ValueError,"checksum"):
            verify_dataset(data)

    def test_nonfinite_prices_fail_entire_cohort(self):
        rows=sample()
        rows[0]["entry_close"]=float("inf")
        out=prepared(rows)
        self.assertEqual(out["manifest"]["included_rows"],210)


class FactorTests(unittest.TestCase):
    def test_rank_spearman_ties_and_constants(self):
        self.assertAlmostEqual(spearman_ic([1,2,3],[3,2,1]),-1)
        self.assertAlmostEqual(spearman_ic([1,2,3],[2,3,4]),1)
        self.assertIsNone(spearman_ic([1,1,1],[2,3,4]))
        self.assertIsNone(spearman_ic([1],[2]))

    def test_positive_negative_constant_and_missing_factor_diagnostics(self):
        audit=factor_diagnostics(prepared(),exploration_end="2026-08-22")
        self.assertEqual(audit["nonoverlapping_evaluated_dates"],4)
        self.assertEqual(audit["omitted_overlapping_dates"],18)
        results=audit["factor_diagnostics"]
        self.assertAlmostEqual(results["technical_score"]["average_rank_ic"],1)
        self.assertAlmostEqual(results["smc_score"]["average_rank_ic"],-1)
        self.assertEqual(results["swing_score"]["usable_nonoverlapping_dates"],0)
        self.assertEqual(results["swing_score"]["dates_constant_factor_or_target"],4)
        self.assertEqual(results["long_term_score"]["missing_factor_tickers"],20)
        self.assertEqual(results["long_term_score"]["dates_insufficient_factor_pairs"],4)
        self.assertAlmostEqual(
            results["technical_score"]["mean_top20_advantage_vs_original_score"],0)
        self.assertLess(results["smc_score"]["mean_top20_advantage_vs_original_score"],0)
        self.assertFalse(audit["holdout_or_forward_performance_approved"])
        self.assertFalse(audit["orders_enabled"])

    def test_same_cohort_comparison_and_early_exploration_cutoff(self):
        history=sample()
        dataset=prepared(history)
        a=factor_diagnostics(dataset,exploration_end="2026-08-12")
        later=sample()
        for row in later:
            if row["as_of_date"]>"2026-08-12":
                row["exit_close"]=1000
        b=factor_diagnostics(prepared(later),exploration_end="2026-08-12")
        self.assertEqual(a["factor_diagnostics"],b["factor_diagnostics"])
        self.assertEqual(a["nonoverlapping_evaluated_dates"],2)

    def test_exploration_rejects_invalid_dates_and_pair_limits(self):
        data=prepared()
        with self.assertRaisesRegex(ValueError,"Exploration end"):
            factor_diagnostics(data,exploration_end="2027-01-01")
        for min_pairs in (0,101,True):
            with self.assertRaises(ValueError):
                factor_diagnostics(data,exploration_end="2026-08-10",
                                   min_pairs=min_pairs)
        with self.assertRaises(ValueError):
            factor_diagnostics(data,exploration_end="2026-08-10",
                               top_fraction=1.0)

    def test_factor_missingness_is_not_silently_imputed(self):
        data=factor_diagnostics(prepared(),exploration_end="2026-08-22",
                                min_pairs=5)
        result=data["factor_diagnostics"]["long_term_score"]
        self.assertEqual(result["factor_availability_rate"],.5)
        self.assertEqual(result["usable_nonoverlapping_dates"],4)
        self.assertLess(result["usable_nonoverlapping_dates"],22)


class CliTests(unittest.TestCase):
    def test_neon_requires_explicit_auth_and_bounded_window(self):
        with patch.dict(os.environ,{"RESEARCH_EXPORT_READONLY":"no"}):
            with self.assertRaises(PermissionError):
                cli.read_existing_neon_scores("mock",start=date(2026,8,1),
                                              end=date(2026,8,5))
        with patch.dict(os.environ,{"RESEARCH_EXPORT_READONLY":"yes"}):
            with self.assertRaises(ValueError):
                cli.read_existing_neon_scores("",start=date(2026,8,1),
                                             end=date(2026,8,5))
            with self.assertRaisesRegex(ValueError,"120 days"):
                cli.read_existing_neon_scores("mock",start=date(2026,1,1),
                                             end=date(2026,8,1))

    def test_neon_query_is_enforced_readonly_and_overflow_fails(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=conn.cursor.return_value.__enter__.return_value
        with patch.dict(os.environ,{"RESEARCH_EXPORT_READONLY":"yes"}),\
             patch("psycopg.connect",return_value=conn) as connect:
            cur.fetchmany.return_value=sample(n_dates=1)
            result=cli.read_existing_neon_scores(
                "mock",start=date(2026,8,1),end=date(2026,8,5),max_rows=100)
            self.assertEqual(len(result),10)
            self.assertEqual(connect.call_args.kwargs["options"],
                             "-c default_transaction_read_only=on")
            self.assertEqual(cur.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            self.assertIn("statement_timeout",cur.execute.call_args_list[1].args[0])
            self.assertIn("SELECT",cur.execute.call_args_list[2].args[0])
            self.assertEqual(cur.fetchmany.call_args.args,(101,))
            cur.fetchmany.return_value=sample(n_dates=12)
            with self.assertRaisesRegex(ValueError,"row cap"):
                cli.read_existing_neon_scores(
                    "mock",start=date(2026,8,1),end=date(2026,8,5),max_rows=100)

    def test_local_offline_prepare_and_factor_cli_no_neon(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/"source.json"
            dataset=root/"dataset.json"
            result=root/"factor.json"
            source.write_text(json.dumps(sample(),ensure_ascii=False),encoding="utf-8")
            with patch.dict(os.environ,{"RESEARCH_EXPORT_READONLY":"no"}),\
                 patch.object(cli,"read_existing_neon_scores",
                              side_effect=AssertionError("offline cannot query Neon")):
                with patch("sys.argv",["pipeline","prepare","--source-json",str(source),
                       "--start","2026-08-01","--end","2026-08-22",
                       "--label-cutoff","2026-10-31","--output",str(dataset)]):
                    cli.main()
                with patch("sys.argv",["pipeline","factors","--dataset",str(dataset),
                       "--exploration-end","2026-08-22","--output",str(result)]):
                    cli.main()
            data=json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(data["nonoverlapping_evaluated_dates"],4)
            self.assertFalse(data["orders_enabled"])


if __name__=="__main__":
    unittest.main()
