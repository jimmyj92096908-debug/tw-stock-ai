"""Offline owner 2022 all 30 >=6 day source-gap review queue regression."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2022_116_internal_source_absence_triage import (
    triage_internal_source_absences,full_six_plus_source_gap_queue,
)
from tests.test_twse_2022_116_internal_source_absence_triage import (
    synthetic_owner_116,
)


def fake_30():
    roster,days,baseline,signatures=synthetic_owner_116()
    observations={d:set(s) for d,s in baseline.items()}
    for sid in roster[:30]:
        for d in days[30:36]:
            observations[d].remove(sid)
    old=triage_internal_source_absences(
        roster,days,observations,enforce_owner_receipt=True)
    assert old["source_observation_gap_count_signatures"][
        "six_or_more_day_run_count"]==30
    return roster,days,observations,old


class LongGapQueue2022OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=fake_30()

    def test_recovers_all_30_6plus_runs_not_only_two_samples(self):
        r,d,observed,old=self.inputs
        queue=full_six_plus_source_gap_queue(
            r,d,observed,previous_authenticated_116_report=old)
        self.assertEqual(queue["at_least_six_unobserved_source_day_run_count"],30)
        self.assertEqual(queue["underlying_116_source_absence_stocks"],116)
        self.assertEqual(queue["underlying_all_absent_source_day_runs"],146)
        self.assertTrue(queue["all_30_long_source_absence_runs_recovered_from_source"])
        items=queue["owner_private_long_run_official_halt_check_queue"]
        self.assertEqual(len(items),30)
        self.assertEqual(len({x["stock_id"] for x in items}),30)
        self.assertTrue(all(x["unobserved_consecutive_source_days"]==6 for x in items))
        self.assertTrue(all(x["first_unobserved_source_day"]==d[30].isoformat()
                            for x in items))
        self.assertTrue(all(x["last_unobserved_source_day"]==d[35].isoformat()
                            for x in items))
        self.assertTrue(all(x["confirmed_official_halt_for_these_dates"] is False
                            for x in items))
        self.assertFalse(queue["paid_service_used"])
        self.assertEqual(queue["production_neon_writes"],0)
        self.assertEqual(queue["line_messages_sent"],0)
        self.assertEqual(queue["model_release"],"BLOCKED")
        self.assertTrue(queue["official_halt_or_resumption_not_checked_by_this_offline_step"])
        self.assertTrue(queue["source_day_absence_not_proof_of_exchange_trading_obligation"])
        self.assertNotIn("raw_price",str(queue))
        self.assertNotIn("close",str(queue))

    def test_exact_previous_116_owner_receipt_required(self):
        r,d,observed,old=self.inputs
        changed=deepcopy(old)
        changed["source_observation_gap_count_signatures"][
            "six_or_more_day_run_count"]=29
        with self.assertRaises(ValueError):
            full_six_plus_source_gap_queue(
                r,d,observed,previous_authenticated_116_report=changed)
        changed=deepcopy(old)
        changed["private_2022_current_stock_internal_absence_research_rows"][0][
            "stock_id"]="1589"
        with self.assertRaises(ValueError):
            full_six_plus_source_gap_queue(
                r,d,observed,previous_authenticated_116_report=changed)
        with self.assertRaises(ValueError):
            full_six_plus_source_gap_queue(
                r,d,observed,previous_authenticated_116_report=None)

    def test_prevent_fictitious_30_runs_and_foreign_stock_source(self):
        r,d,observed,old=self.inputs
        changed=dict(observed)
        changed[d[31]]=set(changed[d[31]])|{r[0]}
        with self.assertRaises(ValueError):
            full_six_plus_source_gap_queue(
                r,d,changed,previous_authenticated_116_report=old)
        changed=dict(observed)
        changed[d[31]]=set(changed[d[31]])|{"1589"}
        with self.assertRaises(ValueError):
            full_six_plus_source_gap_queue(
                r,d,changed,previous_authenticated_116_report=old)
        with self.assertRaises(ValueError):
            full_six_plus_source_gap_queue(
                r,d,observed,previous_authenticated_116_report=old,
                expected_long_run_count=36)
        with self.assertRaises(ValueError):
            full_six_plus_source_gap_queue(
                r,d,observed,previous_authenticated_116_report=old,
                expected_long_run_count=29)

    def test_cli_default_no_secrets_or_authorized_db_mutation(self):
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        for key in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(key,None)
        p=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2022_aes_neon_eligible_density_readonly",
             "--help"],cwd=root,env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("--long-gap-queue",p.stdout)
        self.assertIn("--prior-116-report",p.stdout)


if __name__=="__main__":
    unittest.main()
