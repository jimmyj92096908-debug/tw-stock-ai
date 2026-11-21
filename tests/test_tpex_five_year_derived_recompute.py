"""Free-tier, source fingerprint, stock-scoped TPEx derived-only recompute."""
import os
from pathlib import Path
from datetime import date,datetime,timezone
from unittest import TestCase
from unittest.mock import MagicMock,patch
from scripts import tpex_five_year_derived_recompute as m

ROOT=Path(__file__).resolve().parents[1]

def gate(**update):
    g={"tpex_source_days":180,"tpex_eligible":885,
       "database_bytes":350_000_000,"bad_legacy_volume":0,
       "bad_legacy_turnover":0,"tpex_matched":880}
    g.update(update)
    return g

def stock(sid="5520",n=900):
    return {"stock_id":sid,"price_rows":n,"valid_days":n,
            "last_valid":date(2026,11,20),
            "last_source_write":datetime(2026,11,21,tzinfo=timezone.utc)}

class TPExFiveYearDerivedBatchTests(TestCase):
    def test_bounded_selection_and_source_evidence(self):
        selected,total=m.select_budgeted(
            [stock(str(1000+i),900) for i in range(8)],3)
        self.assertEqual([s["stock_id"] for s in selected],
                         ["1000","1001","1002"])
        self.assertEqual(total,2700)
        too_large=stock("1234",1601)
        s,n=m.select_budgeted([too_large,stock("1235",1200)],3)
        self.assertEqual(n,1200)
        self.assertEqual(s[0]["stock_id"],"1235")
        missing=stock("1236",900)
        missing["last_source_write"]=None
        self.assertEqual(m.select_budgeted([missing],3),([],0))
        for invalid in (
           [stock("1234"),stock("1234")],
           [{**stock(),"valid_days":59}],
           [{**stock(),"price_rows":True}],
           [{**stock(),"stock_id":"ABC"}],
           [stock(str(2000+i)) for i in range(21)],
        ):
            with self.subTest(invalid=invalid),self.assertRaises(
                 (ValueError,RuntimeError)):
                m.select_budgeted(invalid)
        for bad in (0,4,True):
            with self.assertRaises(ValueError):
                m.select_budgeted([],bad)

    def test_neon_limit_and_source_quality_stops(self):
        self.assertTrue(m.preflight(gate()))
        for bad in (
            gate(tpex_source_days=99),gate(tpex_eligible=699),
            gate(bad_legacy_volume=1),gate(bad_legacy_turnover=1),
            gate(database_bytes=760_000_000)
        ):
            with self.assertRaises(RuntimeError):
                m.preflight(bad)
        with self.assertRaises(ValueError):
            m.preflight(gate(database_bytes=None))
        self.assertTrue(m.space_safe(700_000_000,5000))
        self.assertFalse(m.space_safe(750_000_000,5000))
        self.assertFalse(m.space_safe(790_000_000,150))
        for bad in (0,5001,True):
            with self.assertRaises(ValueError):
                m.space_safe(300_000_000,bad)

    def test_apply_requires_three_independent_derived_only_gates(self):
        with self.assertRaises(ValueError):
            m.execute("")
        with patch.dict(os.environ,{},clear=True),\
             patch.object(m,"release_snapshot") as snap:
            with self.assertRaises(PermissionError):
                m.execute("protected",apply=True)
            snap.assert_not_called()
        flags={
          "STOCK_TPEX_POSTFLIGHT_DERIVED_ENABLED":"yes",
          "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
          "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED":"yes"}
        for removed in flags:
            with self.subTest(flag=removed),patch.dict(os.environ,
                    {k:v for k,v in flags.items() if k!=removed},clear=True):
                with self.assertRaises(PermissionError):
                    m.execute("protected",apply=True)
        for limit in (0,4,True):
            with self.assertRaises(ValueError):
                m.execute("protected",limit=limit)

    def test_dry_run_never_calculates_or_scores(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        with patch.object(m,"release_snapshot",return_value=gate()),\
             patch.object(m.psycopg,"connect",return_value=conn) as connect,\
             patch.object(m,"choose",return_value=[stock("5520",850)]),\
             patch.object(m,"size",return_value=320_000_000),\
             patch.object(m,"build_adjusted") as build,\
             patch.object(m,"calculate_all") as score:
            r=m.execute("protected",apply=False,limit=1)
        self.assertFalse(r["apply"])
        self.assertEqual(len(r["selected_stocks"]),1)
        self.assertEqual(r["selected_raw_days"],850)
        self.assertEqual(r["repaired_stocks"],[])
        self.assertFalse(r["complete"])
        self.assertFalse(r["raw_price_keys_modified"])
        self.assertFalse(r["raw_price_values_modified"])
        self.assertFalse(r["LINE_messages_sent"])
        self.assertTrue(r["canary_preview_passes_guards"])
        self.assertIn("default_transaction_read_only=on",
                      connect.call_args.kwargs["options"])
        build.assert_not_called()
        score.assert_not_called()

    def test_exact_one_stock_recalculates_derivatives_and_score_only(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        source={"rows":850,"volume_sum":10000,"turnover_sum":250000,
                "newest_ingest":datetime(2026,11,21,tzinfo=timezone.utc)}
        flags={
          "STOCK_TPEX_POSTFLIGHT_DERIVED_ENABLED":"yes",
          "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
          "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED":"yes"}
        with patch.dict(os.environ,flags),\
             patch.object(m,"release_snapshot",return_value=gate()),\
             patch.object(m.psycopg,"connect",return_value=conn),\
             patch.object(m,"choose",return_value=[stock("5520",850)]),\
             patch.object(m,"size",return_value=340_000_000),\
             patch.object(m,"raw_proof",side_effect=[source,source]),\
             patch.object(m,"build_adjusted",return_value=850) as adjusted,\
             patch.object(m,"build_technicals",return_value=850) as tech,\
             patch.object(m,"build_smc",return_value=850) as smc,\
             patch.object(m,"verify_derived") as checked,\
             patch.object(m,"calculate_all",return_value=1) as score,\
             patch.object(m,"verify_latest_score") as latest:
            r=m.execute("protected",apply=True,limit=1)
        self.assertEqual(len(r["repaired_stocks"]),1)
        self.assertTrue(r["repaired_stocks"][0]["source_fingerprint_unchanged"])
        self.assertFalse(r["raw_price_keys_modified"])
        self.assertFalse(r["global_historical_factor_100_percent_verified"])
        adjusted.assert_called_once()
        tech.assert_called_once()
        smc.assert_called_once()
        checked.assert_called_once()
        score.assert_called_once_with("protected",stocks=[("tpex","5520")],
                                     missing_only=False)
        latest.assert_called_once()

    def test_derived_worker_has_no_raw_price_write_and_only_manual_job(self):
        import inspect
        source=inspect.getsource(m)
        for mutation in ("UPDATE public.daily_prices",
                         "DELETE FROM public.daily_prices",
                         "INSERT INTO public.daily_prices",
                         "LINE_CHANNEL_ACCESS_TOKEN","place_order"):
            self.assertNotIn(mutation,source)
        workflow=(ROOT/".github/workflows/tpex-five-year-derived-batch.yml").read_text()
        self.assertIn("  workflow_dispatch:",workflow)
        self.assertIn("default: false",workflow)
        self.assertNotIn("  push:",workflow)
        self.assertNotIn("  schedule:",workflow)
        self.assertIn("inputs.apply == true",workflow)
        self.assertIn("twstock-indicator-catchup",workflow)
        self.assertIn("twstock-tpex-dated-official-history",workflow)
        for x in ("STOCK_TPEX_POSTFLIGHT_DERIVED_ENABLED",
                  "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED",
                  "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED"):
            self.assertIn(x,workflow)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",workflow)
        self.assertIn("tpex_five_year_derived_recompute.py",workflow)
