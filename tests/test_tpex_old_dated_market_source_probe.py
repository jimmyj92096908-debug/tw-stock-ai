"""Dated TPEx multi-year market-wide source proof, no writes."""
from datetime import date
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import tpex_old_dated_market_source_probe as p

ROOT=Path(__file__).resolve().parents[1]

class TPExOldDatedMarketSourceProbeTests(TestCase):
    def test_exact_two_source_dates_and_readonly_budget(self):
        self.assertEqual(p.DAYS,(date(2025,12,31),date(2022,12,30)))
        self.assertEqual(p.MAX_DATE_REQUESTS,2)
        self.assertEqual(p.MIN_INDEPENDENT_STOCKS,10)
        self.assertEqual(p.COUNT_SQL.strip().upper().split()[0],"SELECT")
        self.assertNotIn("INSERT ",p.COUNT_SQL.upper())
        with self.assertRaises(ValueError):
            p.run("")

    def test_unverified_dates_and_less_than_ten_known_closes_rejected(self):
        fake=MagicMock()
        cur=fake.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=(9,)
        with self.assertRaisesRegex(ValueError,"Fewer than ten"):
            p.source_day_evidence(fake,date(2025,12,31),fetcher=MagicMock())
        with self.assertRaisesRegex(ValueError,"Unknown"):
            p.source_day_evidence(fake,date(2024,12,31),fetcher=MagicMock())

    def test_98pct_and_trusted_cohort_proof(self):
        fake=MagicMock()
        cur=fake.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=(18,)
        approved=[{"market":"tpex","stock_id":str(1000+i)} for i in range(600)]
        source=MagicMock(return_value={"bars":approved})
        with patch.object(p,"load_allowed",
                          return_value={("tpex",str(1000+i)) for i in range(900)}),\
             patch.object(p,"select_candidates",return_value=approved) as select,\
             patch.object(p,"verify_source_date",return_value={
                 "compared":18,"matched":18,"mismatched":0}):
            x=p.source_day_evidence(fake,date(2025,12,31),fetcher=source)
        self.assertTrue(x["source_verified"])
        self.assertEqual(x["same_date_compared"],18)
        self.assertEqual(x["exact_matching_closes"],18)
        self.assertEqual(x["qualified_official_market_stocks"],600)
        self.assertEqual(select.call_args.kwargs["minimum"],540)
        source.assert_called_once_with(date(2025,12,31))

    def test_readonly_report_rejects_false_alpha_and_false_provenance(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=(310_000_000,)
        evidence={"source_verified":True,"status":"verified"}
        with patch.object(p.psycopg,"connect",return_value=conn) as connect,\
             patch.object(p,"source_day_evidence",side_effect=[
                 {**evidence,"date":"2025-12-31"},
                 {**evidence,"date":"2022-12-30"}]) as verify:
            report=p.run("protected",fetcher=MagicMock())
        self.assertEqual(verify.call_count,2)
        self.assertTrue(report["all_old_dates_verified"])
        self.assertFalse(report["raw_prices_modified"])
        self.assertFalse(report["factor_scores_modified"])
        self.assertFalse(report["trading_enabled"])
        self.assertFalse(report["LINE_messages_sent"])
        self.assertEqual(report["official_dates_requested"],2)
        self.assertIn("default_transaction_read_only=on",connect.call_args.kwargs["options"])
        verify.reset_mock()
        with patch.object(p.psycopg,"connect",return_value=conn),\
             patch.object(p,"source_day_evidence",side_effect=ValueError("No historical data")):
            report=p.run("protected",fetcher=MagicMock())
        self.assertFalse(report["all_old_dates_verified"])
        self.assertTrue(all(row["status"]=="rejected" for row in report["results"]))

    def test_exact_once_only_no_prod_writes(self):
        w=(ROOT/".github/workflows/tpex-old-dated-market-probe.yml").read_text(encoding="utf-8")
        self.assertIn("  push:",w)
        self.assertIn(".github/tpex-old-dated-market-readonly-probe-20261121.txt",w)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",w)
        self.assertIn("  workflow_dispatch:",w)
        self.assertNotIn("  schedule:",w)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",w)
        self.assertNotIn("--apply",w)
        self.assertIn("tpex_old_dated_market_source_probe.py",w)
