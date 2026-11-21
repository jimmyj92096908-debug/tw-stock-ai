"""Only verified actual TPEx price-session counts; no IPO-date guesswork."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from scripts import tpex_short_history_gap_audit as audit


def row(band,n,first="2026-08-19",last="2026-11-18",depth=None):
    result={
        "band":band,"stocks":n,
        "earliest_observed_start":date.fromisoformat(first),
        "latest_observed_start":date.fromisoformat(last),
        "latest_market_date":date(2026,11,20),
        "at_least_120":0,"at_least_240":0,
        "at_least_1000":0,"span_five_years_1000":0,
    }
    result.update(depth or {})
    return result


class FakeConnection:
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def __init__(self,rows):
        self.rows=rows
        self.sql=[]
    def execute(self,sql):
        self.sql.append(sql)
        return self
    def fetchall(self):
        return self.rows


class TPExShortHistoryGapTests(unittest.TestCase):
    def test_fixed_bands_real_trading_days_and_no_ipo_assumptions(self):
        sample=[
            row("0-19",4,"2026-10-27","2026-11-16"),
            row("20-29",3),
            row("30-39",3),
            row("40-49",18),
            row("50-59",68,"2026-07-01","2026-09-03"),
            row("60+",787,"2021-01-04","2026-08-20",
                depth={"at_least_120":18,"at_least_240":18,
                       "at_least_1000":16,"span_five_years_1000":16}),
        ]
        output=audit.check_and_aggregate(sample)
        self.assertEqual(output["currently_priced"],883)
        self.assertEqual(output["eligible_real_60_session_history"],787)
        self.assertEqual(output["below_60_session_history"],96)
        self.assertEqual(output["bands"]["50-59"],68)
        self.assertEqual(output["observed_session_depth"]["only_60_to_119"],769)
        self.assertEqual(output["observed_session_depth"]["at_least_120"],18)
        self.assertEqual(output["observed_session_depth"]["at_least_240"],18)
        self.assertEqual(output["observed_session_depth"]["at_least_1000"],16)
        self.assertEqual(output["observed_session_depth"]["at_least_1000_with_five_year_observed_span"],16)
        self.assertFalse(output["full_five_year_official_history_verified"])
        self.assertFalse(output["official_listing_dates_independently_verified"])
        self.assertTrue(output["new_listing_vs_missing_history_not_yet_classified"])
        self.assertFalse(output["inferred_trading_dates_inserted"])
        self.assertFalse(output["orders_enabled"])

    def test_dry_run_query_is_explicitly_read_only(self):
        records=[row("0-19",4),row("50-59",68),row("60+",787)]
        db=FakeConnection(records)
        with patch.object(audit.psycopg,"connect",return_value=db):
            with TemporaryDirectory() as directory:
                path=Path(directory)/"short-history.json"
                output=audit.execute("postgresql://protected",report_path=path)
                doc=json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(doc["currently_priced"],output["currently_priced"])
        self.assertIn("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
                      db.sql)
        self.assertIn("statement_timeout",db.sql[1])
        self.assertIn("COUNT(*) FILTER(WHERE close>0 AND volume>=0)",
                      audit.GAPS_SQL)
        self.assertIn("today.close>0 AND today.volume>=0",audit.GAPS_SQL)
        self.assertIn("valid_days>=120",audit.GAPS_SQL)
        self.assertIn("valid_days>=240",audit.GAPS_SQL)
        self.assertIn("valid_days>=1000",audit.GAPS_SQL)
        self.assertIn("first_observed<=latest_date-INTERVAL '5 years'",audit.GAPS_SQL)
        sql=audit.GAPS_SQL.upper()
        self.assertNotIn("UPDATE PUBLIC",sql)
        self.assertNotIn("DELETE FROM",sql)
        self.assertNotIn("INSERT INTO",sql)

    def test_fail_closed_on_false_history_or_cohort(self):
        for broken in (
            [row("60+",499)],
            [row("60+",780),row("60+",10)],
            [row("60+",787,first="2026-11-20",last="2026-11-18")],
            [row("55-59",883)],
            [row("0-19",-1),row("60+",883)],
            [row("60+",883,depth={"at_least_120":884})],
            [row("60+",883,depth={"at_least_120":10,"at_least_240":11})],
            [row("60+",883,depth={"at_least_120":20,"at_least_240":20,"at_least_1000":20,"span_five_years_1000":21})],
            [row("0-19",2,depth={"at_least_120":1}),row("60+",881)],
            [dict(row("60+",883),at_least_240=None)],
            [dict(row("60+",883),latest_market_date=date(2026,11,1))],
        ):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    audit.check_and_aggregate(broken)
        with self.assertRaises(ValueError):
            audit.check_and_aggregate([])

    def test_uses_existing_monitor_no_new_scheduled_or_price_writes(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/twstock-data-quality-monitor.yml").read_text(
            encoding="utf-8")
        self.assertIn("python scripts/tpex_short_history_gap_audit.py",workflow)
        self.assertIn("tpex-short-history-gap-evidence.json",workflow)
        self.assertIn('depth=x["observed_session_depth"]',workflow)
        self.assertIn('depth["only_60_to_119"]+depth["at_least_120"]',workflow)
        self.assertIn('x["full_five_year_official_history_verified"] is False',workflow)
        self.assertIn("An observed >=5-year span does NOT verify full official 5-year history.",workflow)
        self.assertIn("  schedule:",workflow)
        self.assertNotIn("LINE_CHANNEL",workflow)


if __name__=="__main__":
    unittest.main()
