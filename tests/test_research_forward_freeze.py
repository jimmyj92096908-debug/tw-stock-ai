"""Prospective full-roster freeze: true first-seen, no future-label filtering."""
from __future__ import annotations

from datetime import date,datetime
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.research_forward_freeze import (
    build_frozen_universe,eligible_freeze_time,canonical,MIN_FROZEN_UNIVERSE,
)
from scripts import freeze_prospective_research as runner

ROOT=Path(__file__).resolve().parents[1]
MODEL=json.loads((ROOT/"models/tw-factor-ridge-1-research.json").read_text(encoding="utf-8"))
SIGNAL=date(2026,11,20)
CAPTURE=datetime(2026,11,21,13,30,tzinfo=ZoneInfo("Asia/Taipei"))


def roster(n=50):
    return [
        {
            "market":"twse" if i%2==0 else "tpex",
            "stock_id":str(1000+i),
            "as_of_date":SIGNAL,
            "signal_close":60+i*.2,
            "total_score":55+i*.35,
            "technical_score":55+i*.25,
            "smc_score":52+i*.2,
            "short_term_score":53+i*.1,
            "swing_score":60+i*.15,
            "long_term_score":54+i*.07,
            "coverage_weight":.8,
        }
        for i in range(n)
    ]


def make(rows=None,**kwargs):
    values={"model_sha256":"a"*64,"as_of":CAPTURE,
            "latest_market_date":SIGNAL}
    values.update(kwargs)
    return build_frozen_universe(
        rows if rows is not None else roster(),MODEL,**values)


class ForwardFreezeTests(unittest.TestCase):
    def test_full_cohort_is_precommitted_and_deterministically_ranked(self):
        result=make()
        self.assertEqual(result["universe_count"],50)
        self.assertEqual(result["selected_count"],10)
        self.assertEqual(result["signal_date"],"2026-11-20")
        self.assertEqual(len(result["members"]),50)
        self.assertEqual(sorted(x["model_rank"] for x in result["members"]),list(range(1,51)))
        self.assertEqual(sorted(x["baseline_rank"] for x in result["members"]),list(range(1,51)))
        self.assertEqual(len(result["cohort_sha256"]),64)
        self.assertEqual(result["cohort_sha256"],make()["cohort_sha256"])
        self.assertFalse(result["forward_entry_price_or_return_observed"])
        self.assertFalse(result["eligible_for_model_release"])
        self.assertFalse(result["live_trading_approved"])
        self.assertFalse(result["line_signal_delivery_approved"])
        for x in result["members"]:
            self.assertEqual(len(x["feature_vector"]),12)
            self.assertNotIn("entry_close",x)
            self.assertNotIn("exit_close",x)
            self.assertNotIn("future_return",x)
        self.assertLess(len(canonical(result).encode("utf-8")),runner.MAX_DATA_SIZE)

    def test_historical_retrofreeze_and_future_open_late_rejected(self):
        permitted=eligible_freeze_time(
            SIGNAL,as_of=datetime(2026,11,23,8,10,tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(permitted.hour,8)
        for capture in [
            datetime(2026,11,23,8,30,tzinfo=ZoneInfo("Asia/Taipei")),
            datetime(2026,11,24,7,0,tzinfo=ZoneInfo("Asia/Taipei")),
            datetime(2026,11,20,13,45,tzinfo=ZoneInfo("Asia/Taipei")),
            datetime(2026,11,26,7,0,tzinfo=ZoneInfo("Asia/Taipei")),
        ]:
            with self.subTest(capture=capture):
                with self.assertRaises(ValueError):
                    build_frozen_universe(
                        roster(),MODEL,model_sha256="a"*64,
                        as_of=capture,latest_market_date=SIGNAL)
        with self.assertRaises(ValueError):
            make(latest_market_date=date(2026,11,19))

    def test_entire_day_fails_on_invalid_member_duplicate_or_changed_weights(self):
        bad=roster()
        bad[9]["signal_close"]=0
        with self.assertRaises(ValueError):
            make(bad)
        dupe=roster()
        dupe[1]["stock_id"]=dupe[0]["stock_id"]
        dupe[1]["market"]=dupe[0]["market"]
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            make(dupe)
        mixed=roster()
        mixed[-1]["as_of_date"]=date(2026,11,19)
        with self.assertRaisesRegex(ValueError,"Mixed"):
            make(mixed)
        with self.assertRaises(ValueError):
            make(roster(49))
        wrong={**MODEL,"research_only":False}
        with self.assertRaisesRegex(ValueError,"research-only"):
            build_frozen_universe(roster(),wrong,model_sha256="a"*64,
                                  as_of=CAPTURE,latest_market_date=SIGNAL)
        unfit={**MODEL,"trained_through":"2026-11-20"}
        with self.assertRaises(ValueError):
            build_frozen_universe(roster(),unfit,model_sha256="a"*64,
                                  as_of=CAPTURE,latest_market_date=SIGNAL)

    def test_no_database_write_without_explicit_gate_and_append_only_conflict(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                runner.execute("fake",model_path=ROOT/"models/tw-factor-ridge-1-research.json",
                               apply=True)
        sql=runner.INSERT_SQL.upper()
        self.assertIn("ON CONFLICT (MODEL_VERSION,SIGNAL_DATE) DO NOTHING",sql)
        self.assertNotIn("DO UPDATE",sql)
        self.assertNotIn("DELETE FROM",sql)
        self.assertIn("COHORT_SHA256",sql)
        self.assertIn("REPEATABLE READ",
                      (ROOT/"scripts/freeze_prospective_research.py").read_text())
        ddl=(ROOT/"sql/research_forward_frozen_cohorts.sql").read_text()
        self.assertIn("DEFAULT clock_timestamp()",ddl)
        self.assertIn("PRIMARY KEY (model_version,signal_date)",ddl)


if __name__=="__main__":
    unittest.main()
