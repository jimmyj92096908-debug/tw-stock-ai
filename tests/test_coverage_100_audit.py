"""Conservative full-master stock history + research coverage tests (offline)."""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock,patch

from scripts import coverage_100_audit as module


LATEST="2026-11-20"


def stock(stock_id,*,market="twse",n=100,last=LATEST,
          recent=True,technical=True,smc=True,scored=True):
    if n==0:
        last=None
        recent=technical=smc=scored=False
    return {"market":market,"stock_id":stock_id,"stock_name":"synthetic",
            "price_days":n,"last_close":last,"overall_latest":LATEST,
            "recent":recent,"technical_current":technical,
            "smc_current":smc,"score_current":scored}


class AuditTests(unittest.TestCase):
    def sample(self):
        return [
            stock("1101",n=0),
            stock("1808"),
            stock("1102",n=120,last="2026-10-01",recent=False),
            stock("1103",n=10),
            stock("1104",technical=False),
            stock("1105",smc=False),
            stock("1106",scored=False),
            stock("1107"),
        ]

    def test_mutually_exclusive_blockers_and_true_denominators(self):
        out=module.summarize(self.sample())
        self.assertEqual(out["stock_master_count"],8)
        self.assertEqual(out["currently_eligible_60_day_research_cohort"],4)
        self.assertEqual(out["currently_eligible_matched_composite_stocks"],1)
        self.assertEqual(out["currently_eligible_fraction"],.25)
        self.assertEqual(out["full_master_matched_composite_fraction"],.125)
        for category in module.CATEGORY:
            self.assertEqual(out["status_counts"][category],1)
        self.assertFalse(out["100_percent_all_listed_stocks_claimed"])
        self.assertFalse(out["official_source_has_backfillable_history_proven"])
        self.assertFalse(out["database_written"])
        self.assertFalse(out["orders_enabled"])

    def test_stock_without_valid_close_cannot_claim_current_analysis(self):
        with self.assertRaisesRegex(ValueError,"cannot have current"):
            module.classify({**stock("1101",n=0),"technical_current":True})
        with self.assertRaisesRegex(ValueError,"Inconsistent verified price"):
            module.classify(stock("1101",n=100,last=None))
        with self.assertRaisesRegex(ValueError,"Inconsistent recency"):
            module.classify(stock("1101",n=50, last="2026-11-01",recent=True))
        with self.assertRaisesRegex(ValueError,"trade date"):
            module.classify(stock("1101",last="2026-11-22"))

    def test_duplicate_key_and_mixed_snapshot_dates_fail_closed(self):
        rows=self.sample()
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            module.summarize(rows+[rows[0]])
        with self.assertRaisesRegex(ValueError,"mixed"):
            module.summarize(rows[:-1]+[
                {**rows[-1],"overall_latest":"2026-11-21"}
            ])
        with self.assertRaisesRegex(ValueError,"1..2500"):
            module.summarize([])
        with self.assertRaisesRegex(ValueError,"1..2500"):
            module.summarize(rows*400)

    def test_source_sql_is_read_only_and_uses_last_positive_close(self):
        q=module.AUDIT_SQL.lower()
        self.assertIn("p.close>0",q)
        self.assertIn("last_close",q)
        self.assertIn("and c.total_score is not null",q)
        self.assertIn("h.market",q)
        self.assertIn("limit 2501",q)
        self.assertNotIn("insert into",q)
        self.assertNotIn("delete from",q)
        self.assertNotIn("update public.",q)

    def test_readonly_connection_and_safe_bounded_fetch(self):
        connection=MagicMock()
        connection.__enter__.return_value=connection
        cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchmany.return_value=self.sample()
        with patch("psycopg.connect",return_value=connection) as connect:
            out=module.read_only_snapshot("protected")
        self.assertEqual(out["currently_eligible_matched_composite_stocks"],1)
        self.assertEqual(connect.call_args.kwargs["options"],
                         "-c default_transaction_read_only=on")
        self.assertEqual(cursor.fetchmany.call_args.args,(module.MAX_STOCKS+1,))
        self.assertIn("REPEATABLE READ READ ONLY",cursor.execute.call_args_list[0].args[0])
        self.assertIn("statement_timeout",cursor.execute.call_args_list[1].args[0])
        cursor.fetchmany.return_value=self.sample()*400
        with patch("psycopg.connect",return_value=connection):
            with self.assertRaisesRegex(ValueError,"beyond"):
                module.read_only_snapshot("protected")
        with self.assertRaisesRegex(ValueError,"read-only URL"):
            module.read_only_snapshot("")

    def test_offline_cli_does_not_connect_to_neon(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            inputs=root/"stocks.json"
            outputs=root/"audit.json"
            inputs.write_text(json.dumps(self.sample()),encoding="utf-8")
            with patch.object(module,"read_only_snapshot",
                              side_effect=AssertionError("unexpected DB access")),\
                 patch("sys.argv",["audit","--source-json",str(inputs),
                                   "--output",str(outputs)]):
                module.main()
            data=json.loads(outputs.read_text(encoding="utf-8"))
            self.assertEqual(data["currently_eligible_fraction"],.25)
            self.assertFalse(data["line_messages_sent"])
        with patch.dict(os.environ,{},clear=True),\
             patch("sys.argv",["audit","--read-neon",
                               "--output","/tmp/unused.json"]):
            with self.assertRaises(PermissionError):
                module.main()


if __name__=="__main__":
    unittest.main()
