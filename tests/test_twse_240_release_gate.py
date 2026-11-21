"""Independent schedule source/research gate and 240-day historical evidence."""
from pathlib import Path
from unittest import TestCase

from scripts import twse_240_release_gate as gate
from scripts import twse_240_research_catchup as research

ROOT=Path(__file__).resolve().parents[1]


def state(**changes):
    base={
        "tpex_source_days":91,"twse_source_days":137,
        "legacy_rows":26504,"bad_legacy_volume":0,"bad_legacy_turnover":0,
        "database_bytes":300_000_000,
        "tpex_eligible":880,"tpex_matched":880,
        "tpex_historical_factors_current":880,
        "twse_240_eligible":20,"twse_full_indicators":20,
        "twse_complete_scores":20,
    }
    return {**base,**changes}


class TWSEIndependentReleaseGateTests(TestCase):
    def test_source_requires_completed_tpex_legacy_and_scores(self):
        self.assertTrue(gate.decide("source",state()))
        self.assertFalse(gate.decide("source",state(tpex_source_days=61)))
        self.assertFalse(gate.decide("source",state(tpex_matched=870)))
        self.assertFalse(gate.decide("source",state(tpex_historical_factors_current=879)))
        self.assertIn("missing_historical_derived_date",gate.STATE_SQL)
        self.assertIn("c.score_at>=GREATEST(",gate.STATE_SQL)
        self.assertIn("c.latest_official_ingest",gate.STATE_SQL)
        # Official market-wide dated-session count must remain EW-only:
        # the other trusted TPEx official endpoint tags validate each stock
        # but CANNOT inflate the date-verified independent 91-session gate.
        self.assertIn("AND source='TPEX_DATED_OTC_EW')::int tpex_source_days",
                      gate.STATE_SQL)
        self.assertIn("max(retrieved_at) FILTER(WHERE source IN (",gate.STATE_SQL)
        for official in ("TPEX_DATED_OTC_EW","TPEX_TRADING_STOCK",
                         "TPEX_DAILY_CLOSE_OPENAPI"):
            self.assertIn(official,gate.STATE_SQL)
        for t in ("a","t","s"):
            self.assertIn(f"min({t}.calculated_at)",gate.STATE_SQL)
        # MIN checks source freshness; MAX checks score version ordering.
        for t in ("a","t","s"):
            self.assertIn(f"max({t}.calculated_at)",gate.STATE_SQL)
            field={"a":"adjusted","t":"technical","s":"smc"}[t]
            self.assertIn(f"c.{field}_latest_at",gate.STATE_SQL)
        for t in ("a", "t", "s"):
            self.assertIn(f"{t}.calculated_at IS NULL",gate.STATE_SQL)
        self.assertIn("e.latest_official_ingest",gate.STATE_SQL)
        self.assertFalse(gate.decide("source",state(bad_legacy_volume=1)))
        self.assertFalse(gate.decide("source",state(bad_legacy_turnover=1)))
        self.assertFalse(gate.decide("source",state(twse_source_days=240)))
        self.assertFalse(gate.decide("source",state(legacy_rows=0)))

    def test_research_requires_real_240_day_and_incomplete_long_indicators(self):
        long=state(twse_source_days=245,twse_240_eligible=1000,
                   twse_full_indicators=300,twse_complete_scores=200)
        self.assertTrue(gate.decide("research",long))
        self.assertFalse(gate.decide("research",{
            **long,"twse_source_days":239
        }))
        self.assertFalse(gate.decide("research",{
            **long,"twse_240_eligible":499
        }))
        self.assertTrue(gate.decide("research",{
            **long,"twse_full_indicators":1000,"twse_complete_scores":900
        }))
        self.assertFalse(gate.decide("research",{
            **long,"twse_full_indicators":1000,"twse_complete_scores":1000
        }))

    def test_independent_crons_not_broken_fourth_and_fifth_workflow_run(self):
        files=[
            ".github/workflows/twse-long-history-campaign.yml",
            ".github/workflows/twse-240-research-followon.yml",
        ]
        for name in files:
            with self.subTest(path=name):
                content=(ROOT/name).read_text(encoding="utf-8")
                self.assertIn("  schedule:",content)
                self.assertIn("github.event_name == 'schedule'",content)
                if 'twse-long-history-campaign' in name:
                    self.assertIn('python scripts/twse_five_year_source_gate.py',content)
                else:
                    self.assertIn('python scripts/twse_240_release_gate.py --mode',content)
                self.assertIn("steps.gate.outputs.should_run == 'true'",content)
                self.assertNotIn("  workflow_run:",content)
                self.assertIn("default: false",content)

    def test_research_measurement_requires_full_adjusted_and_ma240(self):
        sql=research.STATE_SQL
        self.assertIn("AND t.ma240 IS NOT NULL",sql)
        self.assertIn("daily_adjusted_prices a",sql)
        self.assertIn(">=e.valid_days",sql)
        self.assertIn("daily_smc s",sql)
        self.assertIn("MIN_VERIFIED_DAYS=240",Path(research.__file__).read_text())
        self.assertNotIn("UPDATE public.daily_prices",sql.upper())
        self.assertIn("SOURCE",gate.STATE_SQL.upper())

    def test_unknown_mode_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"Unknown"):
            gate.decide("unknown",state())
