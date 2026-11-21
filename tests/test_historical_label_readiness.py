"""Leakage-safe tests for historical scored-cohort maturity and comparability."""
from __future__ import annotations

from datetime import date,timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock,patch

from scripts import historical_label_readiness as audit


def cohort(day, *, size=20, mature=20, different_entry=False, different_exit=False,
           exit_days=6):
    d=date.fromisoformat(day)
    entry=(d+timedelta(days=1)).isoformat()
    exit_=(d+timedelta(days=exit_days)).isoformat()
    return {
        "signal_date":day,"scored":size,"mature":mature,
        "distinct_entries":2 if different_entry else (1 if mature else 0),
        "distinct_exits":2 if different_exit else (1 if mature else 0),
        "first_entry":entry if mature else None,
        "last_entry":(d+timedelta(days=2)).isoformat() if different_entry else (entry if mature else None),
        "first_exit":exit_ if mature else None,
        "last_exit":(d+timedelta(days=exit_days+1)).isoformat() if different_exit else (exit_ if mature else None),
    }


def report(rows,*,start="2026-09-01",end="2026-10-31",cutoff="2026-11-20"):
    return audit.assess_historical_labels(rows,start=start,end=end,cutoff=cutoff)


class LabelReadinessTests(unittest.TestCase):
    def test_nonoverlap_and_data_gate_never_prove_alpha(self):
        rows=[
            cohort("2026-09-01"),
            cohort("2026-09-02"),
            cohort("2026-09-09"),
            cohort("2026-09-17"),
            cohort("2026-09-25"),
            cohort("2026-10-03"),
            cohort("2026-10-11"),
            cohort("2026-10-19"),
            cohort("2026-10-27")
        ]
        r=report(rows)
        self.assertEqual(r["fully_labeled_aligned_dates"],9)
        self.assertEqual(r["nonoverlapping_actual_holding_windows"],8)
        self.assertEqual(r["status_counts"]["OVERLAPS_PREVIOUS_SELECTED_EXIT"],1)
        self.assertFalse(r["eligible_for_exploratory_outcome_research"])
        self.assertFalse(r["model_alpha_approved"])
        self.assertTrue(r["previous_model_holdout_not_independent"])
        self.assertFalse(r["orders_enabled"])
        self.assertEqual(len(r["date_summary_sha256"]),64)

    def test_each_signal_day_has_one_exclusive_primary_status(self):
        rows=[
            cohort("2026-09-01",size=4,mature=4),
            cohort("2026-09-08",mature=19),
            cohort("2026-09-15",different_exit=True),
            cohort("2026-09-22",different_entry=True),
            cohort("2026-09-29")
        ]
        r=report(rows)
        counts=r["status_counts"]
        self.assertEqual(counts["INSUFFICIENT_ORIGINAL_SCORED_COHORT"],1)
        self.assertEqual(counts["INCOMPLETE_OR_UNMATURED_FORWARD_LABELS"],1)
        self.assertEqual(counts["UNMATCHED_ACTUAL_ENTRY_OR_EXIT_DATES"],2)
        self.assertEqual(counts["COMPLETE_HOLDING_WINDOW"],1)
        self.assertEqual(r["nonoverlapping_actual_holding_windows"],1)
        self.assertEqual(r["scored_signal_rows"],84)
        self.assertEqual(r["mature_forward_rows"],83)
        self.assertIn("至少 10 個窗",audit.render_markdown(r))

    def test_exploratory_threshold_requires_time_span_as_well_as_windows(self):
        days=[date(2026,9,1)+timedelta(days=x*6) for x in range(10)]
        rows=[cohort(d.isoformat(),exit_days=5) for d in days]
        out=report(rows)
        self.assertEqual(out["nonoverlapping_actual_holding_windows"],10)
        self.assertFalse(out["eligible_for_exploratory_outcome_research"])
        days=[date(2026,9,1)+timedelta(days=x*7) for x in range(10)]
        rows=[cohort(d.isoformat(),exit_days=5) for d in days]
        # The 10th independent observation is Nov 3, so explicitly extend
        # the signal window rather than leaking a date outside its bounds.
        out=report(rows,end="2026-11-10")
        self.assertEqual(out["nonoverlapping_actual_holding_windows"],10)
        self.assertTrue(out["eligible_for_exploratory_outcome_research"])
        self.assertFalse(out["model_alpha_approved"])

    def test_incomplete_or_future_dates_fail_closed(self):
        for bad,pattern in (
            ({"mature":21},"Inconsistent"),
            ({"scored":0,"mature":0,"distinct_entries":0,"distinct_exits":0,
              "first_entry":None,"last_entry":None,"first_exit":None,"last_exit":None},""),
            ({"first_exit":"2026-09-01"},"Malformed"),
            ({"last_exit":"2026-12-15"},"Malformed"),
            ({"distinct_entries":1,"last_entry":"2026-09-03"},"One entry"),
        ):
            if bad.get("scored")==0:
                with self.assertRaisesRegex(ValueError,"Inconsistent"):
                    report([dict(cohort("2026-09-01"),**bad)])
                continue
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError,pattern):
                    report([dict(cohort("2026-09-01"),**bad)])

    def test_rejects_duplicate_signal_days_and_source_limits(self):
        rows=[cohort("2026-09-01")]
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            report(rows+rows)
        with self.assertRaisesRegex(ValueError,"120"):
            report(rows*121)
        with self.assertRaisesRegex(ValueError,"too broad"):
            report(rows,start="2026-01-01",end="2026-10-31")
        with self.assertRaisesRegex(ValueError,"invalid"):
            report(rows,start="2026-09-01",end="2026-10-31",cutoff="2026-10-20")
        with self.assertRaises(ValueError):
            audit.assess_historical_labels(rows,start="2026-09-01",
                                            end="2026-10-31",cutoff="2026-11-20",
                                            min_independent=True)

    def test_sql_enforces_actual_raw_sessions_and_all_date_cohort_not_samples(self):
        q=audit.DAILY_LABEL_SQL.upper()
        self.assertIn("LEAD(P.TRADE_DATE,1)",q)
        self.assertIn("LEAD(P.TRADE_DATE,6)",q)
        self.assertIn("LEAD(A.CLOSE,1)",q)
        self.assertIn("LEAD(A.CLOSE,6)",q)
        self.assertIn("LEFT JOIN SESSIONS",q)
        self.assertIn("COUNT(*) FILTER(WHERE USABLE IS TRUE)",q)
        self.assertIn("COUNT(DISTINCT ENTRY_DATE)",q)
        self.assertIn("ORDER BY SIGNAL_DATE",q)
        self.assertIn("LIMIT 121",q)
        self.assertNotIn("INSERT INTO",q)
        self.assertNotIn("UPDATE PUBLIC.",q)

    def test_readonly_neon_requires_flag_and_bounded_query(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                audit.readonly_aggregate("fake",start="2026-09-01",
                                         end="2026-10-31",cutoff="2026-11-20")
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchmany.return_value=[cohort("2026-09-01")]
        with patch.dict(os.environ,{"HISTORICAL_RESEARCH_LABEL_READONLY":"yes"}),\
             patch("psycopg.connect",return_value=conn) as connect:
            records=audit.readonly_aggregate(
                "fake",start="2026-09-01",end="2026-10-31",cutoff="2026-11-20")
        self.assertEqual(len(records),1)
        self.assertEqual(connect.call_args.kwargs["options"],
                         "-c default_transaction_read_only=on")
        self.assertEqual(cur.fetchmany.call_args.args,(121,))
        self.assertIn("REPEATABLE READ READ ONLY",cur.execute.call_args_list[0].args[0])
        self.assertIn("statement_timeout",cur.execute.call_args_list[1].args[0])
        self.assertEqual(cur.execute.call_args_list[2].args[1],
                         ("2026-11-20","2026-09-01","2026-10-31"))

    def test_offline_cli_creates_safe_json_and_markdown(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            inp,out,md=[root/x for x in ("records.json","report.json","report.md")]
            inp.write_text(json.dumps([cohort("2026-09-01")]),encoding="utf-8")
            with patch("sys.argv",["runner","--source-json",str(inp),
                                   "--start","2026-09-01","--end","2026-10-31",
                                   "--cutoff","2026-11-20",
                                   "--output-json",str(out),"--output-md",str(md)]),\
                 patch.object(audit,"readonly_aggregate",
                              side_effect=AssertionError("No Neon in offline mode")):
                audit.main()
            result=json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(result["eligible_for_exploratory_outcome_research"])
            self.assertIn("不是新模型回測績效",md.read_text(encoding="utf-8"))


if __name__=="__main__":
    unittest.main()
