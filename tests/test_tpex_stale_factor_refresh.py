"""Historical TPEx dates must invalidate stale latest-day factors and scores."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime,timezone,date
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from scripts import tpex_stale_factor_refresh as refresh


def proof(**overrides):
    return {
        "tpex_source_days":91, "tpex_eligible":820,"tpex_matched":820,
        "legacy_rows":26504,"bad_legacy_volume":0,
        "bad_legacy_turnover":0,"database_bytes":280_000_000,
        **overrides,
    }


def stock():
    return {
        "stock_id":"6488","price_rows":91,"valid_days":90,
        "last_valid":date(2026,11,20),
    }


class StubCursor:
    def __init__(self,connection):
        self.connection=connection
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def execute(self,sql,params=None):
        self.connection.queries.append((sql,params))


class StubConnection:
    def __init__(self):
        self.queries=[]
        self.commits=0
        self.rollbacks=0
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def cursor(self):
        return StubCursor(self)
    def transaction(self):
        return nullcontext()
    def commit(self):
        self.commits+=1
    def rollback(self):
        self.rollbacks+=1


class BackfilledTPExFactorRefreshTests(unittest.TestCase):
    def test_official_history_and_legacy_source_quality_preflight(self):
        self.assertTrue(refresh.release_ready(proof()))
        self.assertFalse(refresh.release_ready(proof(tpex_source_days=61)))
        self.assertFalse(refresh.release_ready(proof(tpex_matched=819)))
        self.assertFalse(refresh.release_ready(proof(bad_legacy_volume=1)))
        self.assertFalse(refresh.release_ready(proof(bad_legacy_turnover=1)))
        self.assertFalse(refresh.release_ready(proof(tpex_eligible=699)))
        with self.assertRaisesRegex(RuntimeError,"size guard"):
            refresh.release_ready(proof(database_bytes=810_000_000))
        with self.assertRaises(ValueError):
            refresh.release_ready(proof(database_bytes="unknown"))

    def test_dry_run_does_not_recompute_or_modify_any_table(self):
        db=StubConnection()
        with (
            patch.object(refresh,"release_snapshot",return_value=proof()),
            patch.object(refresh.psycopg,"connect",return_value=db),
            patch.object(refresh,"choose",return_value=[stock()]),
            patch.object(refresh,"build_adjusted") as adj,
            patch.object(refresh,"build_technicals") as tech,
            patch.object(refresh,"build_smc") as smc,
            patch.object(refresh,"calculate_all") as scores,
        ):
            result=refresh.execute("postgresql://protected",apply=False)
        self.assertTrue(result["release_preflight_ready"])
        self.assertEqual(result["preview_pending_first_batch"],1)
        self.assertFalse(result["raw_prices_modified"])
        self.assertFalse(result["line_messages_sent"])
        adj.assert_not_called()
        tech.assert_not_called()
        smc.assert_not_called()
        scores.assert_not_called()

    def test_apply_requires_three_gates_and_bounded_windows(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,"Three"):
                refresh.execute("protected",apply=True)
        for bad in (-1,6,True):
            with self.assertRaisesRegex(ValueError,"Unsafe"):
                refresh.execute("protected",rounds=bad)
        with self.assertRaisesRegex(ValueError,"Three"):
            refresh.execute("protected",apply=True,rounds=0)
        for bad in (0,21,True):
            with self.assertRaisesRegex(ValueError,"Unsafe"):
                refresh.choose(StubConnection(),limit=bad)

    def test_targeted_repair_rebuilds_all_days_and_rescores_even_existing_score(self):
        db=StubConnection()
        gates={
            "STOCK_TPEX_STALE_FACTOR_WRITE_ENABLED":"yes",
            "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
            "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED":"yes",
        }
        original={
            "rows":91,"volume_sum":Decimal("999"),
            "turnover_sum":Decimal("555"),
            "newest_ingest":datetime(2026,11,21,tzinfo=timezone.utc),
        }
        with (
            patch.dict(os.environ,gates),
            patch.object(refresh,"release_snapshot",return_value=proof()),
            patch.object(refresh.psycopg,"connect",return_value=db),
            patch.object(refresh,"choose",side_effect=[[stock()],[]]),
            patch.object(refresh,"raw_proof",return_value=original),
            patch.object(refresh,"build_adjusted",return_value=91) as adjusted,
            patch.object(refresh,"build_technicals",return_value=91) as technical,
            patch.object(refresh,"build_smc",return_value=91) as smc,
            patch.object(refresh,"verify_derived",return_value={"price_rows":91,
                "missing_derived_days":0}) as check,
            patch.object(refresh,"calculate_all",return_value=1) as score,
            patch.object(refresh,"verify_latest_score") as score_check,
        ):
            out=refresh.execute("fake",apply=True,rounds=2)
        self.assertTrue(out["complete"])
        self.assertEqual(len(out["stocks"]),1)
        self.assertFalse(out["raw_prices_modified"])
        adjusted.assert_called_once_with(db,"tpex","6488")
        technical.assert_called_once_with(db,"tpex","6488")
        smc.assert_called_once_with(db,"tpex","6488")
        check.assert_called_once()
        score.assert_called_once_with("fake",stocks=[("tpex","6488")],
                                       missing_only=False)
        score_check.assert_called_once()
        stamp_calls=[(sql,args) for sql,args in db.queries
                     if "UPDATE public.daily_composite_scores" in sql]
        self.assertEqual(len(stamp_calls),1)
        self.assertEqual(stamp_calls[0][1],("6488",date(2026,11,20)))
        self.assertGreaterEqual(db.commits,1)

    def test_fail_closed_when_historical_source_or_score_unverifiable(self):
        gates={
            "STOCK_TPEX_STALE_FACTOR_WRITE_ENABLED":"yes",
            "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes",
            "STOCK_TPEX_STALE_SCORE_WRITE_ENABLED":"yes",
        }
        with (
            patch.dict(os.environ,gates),
            patch.object(refresh,"release_snapshot",return_value=proof(
                bad_legacy_volume=3)),
            patch.object(refresh.psycopg,"connect") as connect,
        ):
            with self.assertRaisesRegex(RuntimeError,"prerequisites unmet"):
                refresh.execute("fake",apply=True)
            connect.assert_not_called()
        db=StubConnection()
        with (
            patch.dict(os.environ,gates),
            patch.object(refresh,"release_snapshot",return_value=proof()),
            patch.object(refresh.psycopg,"connect",return_value=db),
            patch.object(refresh,"choose",return_value=[stock()]),
            patch.object(refresh,"raw_proof",return_value={
                "rows":91,"volume_sum":Decimal(1),
                "turnover_sum":Decimal(2),"newest_ingest":None}),
            patch.object(refresh,"build_adjusted",return_value=91),
            patch.object(refresh,"build_technicals",return_value=91),
            patch.object(refresh,"build_smc",return_value=91),
            patch.object(refresh,"verify_derived",
                         side_effect=RuntimeError("missing historical dates")),
            patch.object(refresh,"calculate_all") as score,
        ):
            with self.assertRaisesRegex(RuntimeError,"missing historical dates"):
                refresh.execute("fake",apply=True,rounds=1)
            score.assert_not_called()

    def test_selector_proves_older_dates_and_unchanged_score_timestamp(self):
        sql=refresh.CANDIDATES_SQL
        self.assertIn("last_source_write",sql)
        self.assertIn("FILTER(WHERE source='TPEX_DATED_OTC_EW')",sql)
        self.assertIn("a.technical_rows<a.price_rows",sql)
        self.assertIn("a.score_at<GREATEST",sql)
        self.assertIn("LEFT JOIN public.daily_adjusted_prices",sql)
        self.assertIn("d.trade_date IS NULL OR t.trade_date IS NULL",sql)
        for factor in ("d", "t", "s"):
            self.assertIn(f"{factor}.calculated_at IS NULL",sql)
            self.assertIn(f"{factor}.calculated_at<a.last_source_write",sql)
        self.assertIn("calculated_at=clock_timestamp()",refresh.STAMP_VERIFIED_SCORE_SQL)
        self.assertIn("c.stock_id=%s AND c.as_of_date=%s",refresh.STAMP_VERIFIED_SCORE_SQL)
        self.assertNotIn("UPDATE public.daily_prices",sql.upper())


if __name__=="__main__":
    unittest.main()
