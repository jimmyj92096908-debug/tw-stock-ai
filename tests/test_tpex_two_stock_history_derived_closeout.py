"""Fixed two-stock TPEx official-history derived-only closeout safety tests."""
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch,MagicMock

from scripts import tpex_two_stock_history_derived_closeout as closeout

ROOT=Path(__file__).resolve().parents[1]


def state(**kwargs):
    x={
      "database_bytes":310_812_672,"tpex_source_days":91,
      "tpex_eligible":879,"tpex_matched":879,
      "tpex_historical_factors_current":877,
      "bad_legacy_volume":140,"bad_legacy_turnover":140,
    }
    x.update(kwargs)
    return x


def claims():
    return [
       {"stock_id":"5520","price_rows":141,"official_monthly_rows":76,
        "legacy_bad_volume":76,"legacy_bad_turnover":76},
       {"stock_id":"6762","price_rows":130,"official_monthly_rows":64,
        "legacy_bad_volume":64,"legacy_bad_turnover":64}
    ]


class TwoStockDerivedOnlyCloseoutTests(TestCase):
    def test_rejects_unverified_or_expanded_cohort(self):
        self.assertTrue(closeout.verify_scope(state(),claims()))
        self.assertEqual(closeout.STOCKS,("5520","6762"))
        for changed_state,changed_claims in (
            (state(database_bytes=800_000_000),claims()),
            (state(tpex_source_days=79),claims()),
            (state(tpex_eligible=880),claims()),
            (state(tpex_matched=878),claims()),
            (state(tpex_historical_factors_current=876),claims()),
            (state(bad_legacy_volume=139),claims()),
            (state(bad_legacy_turnover=139),claims()),
            (state(),claims()[:1]),
            (state(),[{**claims()[0],"stock_id":"9999"},claims()[1]]),
            (state(),[{**claims()[0],"price_rows":59},claims()[1]]),
            (state(),[{**claims()[0],"official_monthly_rows":0},claims()[1]]),
            (state(),[{**claims()[0],"legacy_bad_volume":0},claims()[1]]),
        ):
            with self.subTest(changed_state=changed_state,changed_claims=changed_claims):
                with self.assertRaises(RuntimeError):
                    closeout.verify_scope(changed_state,changed_claims)

    def test_no_apply_without_independent_three_gates(self):
        with self.assertRaises(ValueError):
            closeout.perform("")
        with patch.dict(os.environ,{},clear=True),\
             patch.object(closeout,"read_evidence") as evidence:
            with self.assertRaises(PermissionError):
                closeout.perform("protected",apply=True)
            evidence.assert_not_called()
        gates={
          "STOCK_TPEX_TWO_STOCK_DERIVED_CLOSEOUT_ENABLED":"yes",
          "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
          "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED":"yes"
        }
        for excluded in gates:
            with self.subTest(excluded=excluded),patch.dict(os.environ,
                            {k:v for k,v in gates.items() if k!=excluded},clear=True):
                with self.assertRaises(PermissionError):
                    closeout.perform("protected",apply=True)

    def test_preview_has_no_writer_and_never_claims_success(self):
        before={"n":200000,"volume_sum":100,"turnover_sum":200,
                "first_trade_date":None,"last_trade_date":None}
        with patch.object(closeout,"read_evidence",
                          return_value=(state(),claims(),before)),\
             patch.object(closeout.psycopg,"connect") as connection,\
             patch.object(closeout,"build_adjusted") as build:
            result=closeout.perform("protected",apply=False)
            connection.assert_not_called()
            build.assert_not_called()
        self.assertEqual(result["source_stocks"],["5520","6762"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["raw_prices_modified"])
        self.assertFalse(result["line_messages_sent"])
        self.assertFalse(result["orders_enabled"])
        self.assertFalse(result["paid_plan_requested"])
        self.assertEqual(result["initial_full_historical_factors"],877)
        self.assertEqual(result["initial_legacy_source_missing_adjusted_volume"],140)

    def test_fixed_source_queries_and_no_raw_price_mutations(self):
        import inspect
        src=inspect.getsource(closeout)
        self.assertNotIn("UPDATE public.daily_prices",src)
        self.assertNotIn("DELETE FROM public.daily_prices",src)
        self.assertNotIn("INSERT INTO public.daily_prices",src)
        self.assertNotIn("LINE_CHANNEL",src)
        self.assertIn("verify_derived(conn,stock)",src)
        self.assertIn("verify_latest_score(conn,stock)",src)
        self.assertIn('calculate_all(url,stocks=[("tpex",sid)],missing_only=False)',src)
        self.assertIn('after["tpex_historical_factors_current"]==EXPECTED_ELIGIBLE',src)
        self.assertIn('after["bad_legacy_volume"]==0',src)
        self.assertEqual(closeout.MAX_DB_BYTES,800_000_000)
        self.assertTrue(closeout.GLOBAL_RAW_SQL.strip().upper().startswith("SELECT"))
        self.assertIn("UPDATE public.daily_composite_scores",closeout.STAMP_VERIFIED_SCORE_SQL)

    def test_workflow_bounded_once_and_existing_writer_lock(self):
        content=(ROOT/".github/workflows/tpex-two-stock-history-derived-closeout.yml").read_text(encoding="utf-8")
        marker=".github/tpex-two-stock-derived-closeout-20261121.txt"
        self.assertIn("  workflow_dispatch:",content)
        self.assertIn("  push:",content)
        self.assertIn(marker,content)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",content)
        self.assertIn("steps.release.outputs.approved == 'true'",content)
        self.assertNotIn("  schedule:",content)
        self.assertIn("twstock-indicator-catchup",content)
        self.assertIn("twstock-tpex-dated-official-history",content)
        for flag in (
            "STOCK_TPEX_TWO_STOCK_DERIVED_CLOSEOUT_ENABLED",
            "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED",
            "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED"
        ):
            self.assertIn(flag,content)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",content)
        self.assertIn("--apply --report two-stock-closeout-evidence.json",content)


if __name__=="__main__":
    import unittest
    unittest.main()
