"""No-write quality-monitor milestone tests, including false-alpha guard."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from unittest import TestCase
from unittest.mock import patch

from scripts import research_readonly_milestones as audit


def state(**changes):
    base={
        "tpex_source_days":61,"twse_source_days":137,
        "legacy_rows":26504,"bad_legacy_volume":24895,
        "bad_legacy_turnover":25026,"tpex_eligible":794,
        "tpex_matched":63,"twse_240_eligible":20,
        "twse_full_indicators":20,"twse_complete_scores":20,
        "database_bytes":269000000,
    }
    return {**base,**changes}


def frozen(**changes):
    base={
        "frozen_cohorts":1,"frozen_signal_days":1,
        "first_signal":date(2026,11,20),
        "latest_signal":date(2026,11,20),
        "implausible_frozen_timestamps":0,
    }
    return {**base,**changes}


class ResearchReadOnlyMilestoneTests(TestCase):
    def test_no_write_snapshot_and_explicit_incomplete_scoring(self):
        with (
            patch.object(audit,"snapshot",return_value=state()) as snapshot,
            patch.object(audit,"read_frozen_evidence",return_value=frozen()),
        ):
            with TemporaryDirectory() as directory:
                target=Path(directory)/"milestones.json"
                report=audit.execute("postgresql://readonly",report_path=target)
                self.assertEqual(json.loads(target.read_text())["schema_version"],1)
            self.assertEqual(report["legacy_tpex_units"]["derived_volume_bad_or_missing"],24895)
            self.assertEqual(report["legacy_tpex_units"]["derived_turnover_bad_or_missing"],25026)
            self.assertFalse(report["legacy_tpex_units"]["all_source_units_verified"])
            self.assertEqual(report["future_research"]["immutable_frozen_cohorts"],1)
            self.assertEqual(report["future_research"]["latest_signal_date"],"2026-11-20")
            self.assertFalse(report["future_research"]["independently_verified_positive_alpha"])
            self.assertFalse(report["future_research"]["future_holdout_statistically_validated"])
            self.assertFalse(report["safety"]["orders_enabled"])
            self.assertFalse(report["safety"]["raw_price_updates"])
            snapshot.assert_called_once_with("postgresql://readonly")

    def test_no_research_gate_without_real_source_and_legacy_repairs(self):
        result=audit.report_from_evidence(state(),frozen())
        self.assertFalse(result["official_history"]["twse_240_day_source_gate"])
        self.assertFalse(result["official_history"]["twse_240_day_research_gate"])
        self.assertFalse(result["legacy_tpex_units"]["all_source_units_verified"])
        done=audit.report_from_evidence(
            state(tpex_source_days=91,tpex_matched=794,
                  bad_legacy_volume=0,bad_legacy_turnover=0),
            frozen(frozen_cohorts=2,frozen_signal_days=2,
                   latest_signal=date(2026,11,23)))
        self.assertTrue(done["official_history"]["twse_240_day_source_gate"])
        self.assertTrue(done["legacy_tpex_units"]["all_source_units_verified"])
        self.assertFalse(done["future_research"]["independently_verified_positive_alpha"])

    def test_impossible_statistics_fail_closed(self):
        for broken in (
            state(bad_legacy_volume=26505),
            state(bad_legacy_turnover=-1),
            state(database_bytes="unknown"),
        ):
            with self.assertRaises(ValueError):
                audit.report_from_evidence(broken,frozen())
        with self.assertRaises(ValueError):
            audit.report_from_evidence(state(),frozen(latest_signal="2026-11-20"))
        with self.assertRaises(ValueError):
            audit.report_from_evidence(state(),{})

    def test_monitor_reuses_existing_schedule_not_new_payable_watcher(self):
        workflow=(Path(__file__).resolve().parents[1]/
                  ".github/workflows/twstock-data-quality-monitor.yml").read_text()
        self.assertIn("research_readonly_milestones.py",workflow)
        self.assertIn("twstock-research-milestones.json",workflow)
        self.assertIn("Read-Only",workflow)
        self.assertNotIn("STOCK_FORWARD_RESEARCH_FREEZE_WRITE",workflow)
        self.assertIn("on:\n",workflow)
        self.assertIn("run: pip install",workflow)
        self.assertNotIn("LINE_CHANNEL",workflow)
        self.assertIn("  schedule:",workflow)
