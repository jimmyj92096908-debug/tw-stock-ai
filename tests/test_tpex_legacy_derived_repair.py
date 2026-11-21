"""Guard, scoped cohort and savepoint evidence for legacy TPEx derived repair."""
from contextlib import nullcontext
from decimal import Decimal
import os
from unittest import TestCase
from unittest.mock import patch

from scripts import tpex_legacy_derived_repair as repair


def baseline(size=260_000_000):
    return {"rows": 26_504, "volume_sum": Decimal("123456"),
            "turnover_sum": Decimal("789000.00"), "database_bytes":size}


class FakeCursor:
    def __init__(self):
        self.statement = ""
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def execute(self, query, params=None):
        self.statement = query
    def fetchone(self):
        return {"scored":True}


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.cur = FakeCursor()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def transaction(self):
        return nullcontext()
    def cursor(self):
        return self.cur
    def commit(self):
        self.commits += 1


class LegacyDerivedRepairSafetyTests(TestCase):
    def test_source_scoping_does_not_include_generic_stocks(self):
        self.assertIn("source='TPEX_TRADING_STOCK'", repair.TARGET_SQL)
        self.assertIn("valid_days>=%s", repair.TARGET_SQL)
        self.assertIn("last_price>=d.latest-interval '7 days'", repair.TARGET_SQL)
        self.assertNotIn("UPDATE public.daily_prices", repair.TARGET_SQL)
        self.assertNotIn("INSERT INTO public.daily_prices", repair.TARGET_SQL)
        self.assertIn("volume::numeric*1000*share_adjustment_factor",
                      repair.VERIFY_SQL)
        self.assertEqual((repair.MAX_TARGETS, repair.MAX_WINDOW), (70,10))

    def test_dry_run_never_rebuilds_derived_series(self):
        fake = FakeConnection()
        with (
            patch.object(repair.psycopg,"connect",return_value=fake),
            patch.object(repair,"fingerprint",return_value=baseline()),
            patch.object(repair,"choose_targets",return_value=[
                {"stock_id":"6488","valid_days":70,"last_price":"2026-11-20"}
            ]),
            patch.object(repair,"build_adjusted") as adj,
            patch.object(repair,"build_technicals") as tech,
            patch.object(repair,"build_smc") as smc,
            patch.object(repair,"calculate_all") as score,
        ):
            r = repair.execute("postgresql://localhost/test",apply=False)
        self.assertEqual(r["stocks"][0]["status"],"dry-run")
        self.assertFalse(r["raw_prices_modified"])
        adj.assert_not_called()
        tech.assert_not_called()
        smc.assert_not_called()
        score.assert_not_called()

    def test_apply_requires_explicit_write_gates_and_window(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,"write gates"):
                repair.execute("fake",apply=True)
        with self.assertRaisesRegex(ValueError,"Rescore"):
            repair.execute("fake",rescore=True)
        for bad in (0,11,100):
            with self.assertRaisesRegex(ValueError,"per-run"):
                repair.execute("fake",limit=bad)
        with self.assertRaisesRegex(ValueError,"offset"):
            repair.execute("fake",offset=70)

    def test_gated_derived_repair_and_one_stock_rescore(self):
        fake=FakeConnection()
        targets=[
            {"stock_id":"6488","valid_days":70,"last_price":"2026-11-20"},
            {"stock_id":"8937","valid_days":70,"last_price":"2026-11-20"},
        ]
        gates={
            "STOCK_TPEX_LEGACY_DERIVED_REPAIR_ENABLED":"yes",
            "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
            "STOCK_TPEX_LEGACY_SCORE_RECALC_ENABLED":"yes",
        }
        with (
            patch.dict(os.environ,gates),
            patch.object(repair.psycopg,"connect",return_value=fake),
            patch.object(repair,"fingerprint",return_value=baseline()),
            patch.object(repair,"choose_targets",return_value=targets),
            patch.object(repair,"build_adjusted",return_value=70) as adj,
            patch.object(repair,"build_technicals",return_value=70) as tech,
            patch.object(repair,"build_smc",return_value=70) as smc,
            patch.object(repair,"verify_derived",return_value={"legacy_rows":60}) as verify,
            patch.object(repair,"calculate_all",return_value=1) as score,
        ):
            r=repair.execute("fake",apply=True,rescore=True,offset=1,limit=1)
        self.assertEqual([x["stock_id"] for x in r["stocks"]],["8937"])
        adj.assert_called_once_with(fake,"tpex","8937")
        tech.assert_called_once_with(fake,"tpex","8937")
        smc.assert_called_once_with(fake,"tpex","8937")
        score.assert_called_once_with("fake",stocks=[("tpex","8937")],
                                      missing_only=False)
        verify.assert_called_once()
        self.assertGreaterEqual(fake.commits,2)

    def test_source_audit_failure_prevents_score_rebuild(self):
        fake=FakeConnection()
        gates={"STOCK_TPEX_LEGACY_DERIVED_REPAIR_ENABLED":"yes",
               "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
               "STOCK_TPEX_LEGACY_SCORE_RECALC_ENABLED":"yes"}
        with (
            patch.dict(os.environ,gates),
            patch.object(repair.psycopg,"connect",return_value=fake),
            patch.object(repair,"fingerprint",return_value=baseline()),
            patch.object(repair,"choose_targets",return_value=[
                {"stock_id":"6488","valid_days":70,"last_price":"2026-11-20"}
            ]),
            patch.object(repair,"build_adjusted",return_value=70),
            patch.object(repair,"build_technicals",return_value=70),
            patch.object(repair,"build_smc",return_value=70),
            patch.object(repair,"verify_derived",
                         side_effect=RuntimeError("source unit mismatch")),
            patch.object(repair,"calculate_all") as score,
        ):
            with self.assertRaisesRegex(RuntimeError,"source unit mismatch"):
                repair.execute("fake",apply=True,rescore=True)
        score.assert_not_called()

    def test_free_storage_hard_stop(self):
        fake=FakeConnection()
        class Cursor:
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def execute(self,*_):pass
            def fetchone(self):return baseline(size=810_000_000)
        fake.cur=Cursor()
        with self.assertRaisesRegex(RuntimeError,"Free storage"):
            repair.fingerprint(fake)
