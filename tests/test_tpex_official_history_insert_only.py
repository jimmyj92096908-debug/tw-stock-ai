"""Safety, source provenance and insert-only guards for official TPEx history."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import os
from unittest import TestCase
from unittest.mock import MagicMock, patch

from scripts import tpex_official_history_insert_only as src


def official(stock="2330",month="2026-07",day="01",close=100):
    d=month+"-"+day
    return {
        "stock_id":stock,"trade_date":d,
        "open":close,"high":close+3,"low":close-3,"close":close,
        "volume":10000,"turnover":1000000,"change":0.5,"transactions":100,
        "source":"TPEX_TRADING_STOCK",
    }


class TPExInsertOnlyTests(TestCase):
    def test_source_window_never_future_and_exact_five_months(self):
        months=src.months_to_fetch(date(2026,11,21),number=5)
        self.assertEqual([m.strftime("%Y-%m") for m in months],
                         ["2026-07","2026-08","2026-09","2026-10","2026-11"])
        self.assertEqual(src.months_to_fetch(date(2026,1,5),number=2),
                         [date(2025,12,1),date(2026,1,1)])
        with self.assertRaises(ValueError):
            src.months_to_fetch(date(2026,11,21),number=6)

    def test_validates_official_month_and_skips_nontraded_not_synthesized(self):
        rows=[
            official(month="2026-07",day="01"),
            {**official(month="2026-07",day="02"),"close":None},
        ]
        rows[1]["open"]=None
        rows[1]["high"]=None
        rows[1]["low"]=None
        approved=src.validate_official_month("2330",date(2026,7,1),rows,
                                             today=date(2026,11,21))
        self.assertEqual(len(approved),1)
        self.assertEqual(approved[0]["market"],"tpex")
        self.assertEqual(approved[0]["trade_date"],"2026-07-01")

    def test_rejects_source_wrong_symbol_wrong_date_future_and_duplicates(self):
        original=official(month="2026-07",day="05")
        cases=[
            [{**original,"stock_id":"9999"}],
            [{**original,"source":"UNTRUSTED"}],
            [{**original,"trade_date":"2026-08-05"}],
            [{**original,"trade_date":"2026-07-30"}],
            [original,dict(original)],
            [{**original,"high":90}],
            [{**original,"close":-10}],
            [{**original,"volume":-1}],
        ]
        for rows in cases:
            with self.subTest(rows=str(rows)):
                with self.assertRaises(ValueError):
                    src.validate_official_month("2330",date(2026,7,1),rows,
                                                today=date(2026,7,21))
        with self.assertRaises(ValueError):
            src.validate_official_month("2330",date(2026,7,1),
                                        [original]*121,today=date(2026,8,1))

    def test_official_get_called_bounded_and_source_validated(self):
        with patch.object(src.tpex_market_data,"fetch_month",
                          return_value=[official(stock="2330",month="2026-11",day="01")]) as get,\
             patch.object(src.time,"sleep") as sleep:
            with self.assertRaisesRegex(ValueError,"mismatched"):
                src.fetch_verified_history("2330",today=date(2026,11,21),
                                           months=2)
        self.assertEqual(get.call_count,1)
        sleep.assert_not_called()
        with patch.object(src.tpex_market_data,"fetch_month",
                          side_effect=[
                              [official(stock="2330",month="2026-10",day="01")],
                              [official(stock="2330",month="2026-11",day="01")]
                          ]) as get,patch.object(src.time,"sleep") as sleep:
            rows=src.fetch_verified_history("2330",today=date(2026,11,21),months=2)
        self.assertEqual(len(rows),2)
        self.assertEqual(get.call_count,2)
        sleep.assert_called_once_with(2.0)

    def test_one_time_ten_stock_marker_is_bounded_and_closes_scores(self):
        source=(Path(__file__).resolve().parents[1]/
                ".github/workflows/tpex-official-insert-only-history.yml"
                ).read_text(encoding="utf-8")
        marker=".github/tpex-official-history-authorized-batch10-20261121.txt"
        self.assertIn(marker,source)
        self.assertIn(".github/tpex-official-history-authorized-batch10-v2-20261121.txt",source)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",source)
        self.assertIn("fetch-depth: 2",source)
        self.assertIn('echo "extended=true" >> "$GITHUB_OUTPUT"',source)
        self.assertIn("steps.batch.outputs.extended",source)
        self.assertNotIn("contains(github.event.head_commit.added",source)
        self.assertIn('limit=10',source)
        self.assertIn('limit=2',source)
        self.assertIn('--months 5',source)
        self.assertIn("group: ${{ github.event_name == 'push' && 'twstock-indicator-catchup'",source)
        self.assertIn("STOCK_TPEX_INSERT_ONLY_HISTORY_ENABLED",source)
        self.assertIn("STOCK_NEW_ELIGIBLE_SCORE_WRITE_ENABLED",source)
        self.assertIn("new_eligible_score_followon.py --apply --limit 5",source)
        self.assertIn("snapshot(os.environ[\"DATABASE_URL\"])",source)
        self.assertIn('cohort["matched_current"]==cohort["eligible"]',source)
        self.assertEqual(source.count("    - cron:"),1)
        self.assertIn('if-no-files-found: ignore',source)
        self.assertIn("tpex-new-eligible-followon-second.json",source)

    def test_insert_sql_preserves_existing_primary_keys(self):
        sql=src.PRICE_INSERT_ONLY_SQL.upper()
        self.assertIn("ON CONFLICT (MARKET,STOCK_ID,TRADE_DATE) DO NOTHING",sql)
        self.assertNotIn("DO UPDATE",sql)
        self.assertNotIn("DELETE",sql)
        self.assertNotIn("TRUNCATE",sql)
        self.assertIn("WHERE H.VALID_DAYS BETWEEN 1 AND 59",src.CANDIDATES_SQL.upper())
        self.assertEqual(src.MAX_STOCKS,10)
        self.assertEqual(src.MAX_MONTHLY_SOURCE_CALLS,50)

    def test_no_write_without_explicit_gate_and_bounded_requests(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                src.run("fake",apply=True,limit=2,today=date(2026,11,21))
        with self.assertRaises(ValueError):
            src.run("fake",apply=False,limit=11)
        with self.assertRaises(ValueError):
            src.run("fake",apply=False,limit=10,months=6)
        with self.assertRaises(ValueError):
            src.run("fake",apply=False,limit=0)

    def test_dry_run_only_reads_and_does_not_touch_http(self):
        fakeconn=MagicMock()
        fakeconn.__enter__.return_value=fakeconn
        stock={"market":"tpex","stock_id":"2330","valid_days":1,
               "newest":date(2026,11,20)}
        with patch.object(src.psycopg,"connect",return_value=fakeconn),\
             patch.object(src,"_size_guard",return_value=230000000),\
             patch.object(src,"select_candidates",return_value=[stock]),\
             patch.object(src,"fetch_verified_history") as network,\
             patch.object(src,"_state") as state:
            result=src.run("fake",apply=False,limit=1,today=date(2026,11,21))
        self.assertEqual(result["selected"],1)
        self.assertEqual(result["stocks"][0]["status"],"dry-run")
        self.assertFalse(result["price_existing_keys_overwritten"])
        network.assert_not_called()
        state.assert_not_called()

    def test_bounded_writes_only_new_keys_and_reports_real_growth(self):
        fakeconn=MagicMock()
        fakeconn.__enter__.return_value=fakeconn
        stock={"market":"tpex","stock_id":"2330","valid_days":1,
               "newest":date(2026,11,20)}
        official_rows=[src.validate_official_month("2330",date(2026,11,1),
                       [official(month="2026-11",day="20")],
                       today=date(2026,11,21))[0]]
        with patch.dict(os.environ,{"STOCK_TPEX_INSERT_ONLY_HISTORY_ENABLED":"yes"}),\
             patch.object(src.psycopg,"connect",return_value=fakeconn),\
             patch.object(src,"_size_guard",return_value=230000000),\
             patch.object(src,"select_candidates",return_value=[stock]),\
             patch.object(src,"fetch_verified_history",return_value=official_rows),\
             patch.object(src,"_count",side_effect=[1,2]),\
             patch.object(src,"_state") as state:
            out=src.run("fake",apply=True,limit=1,today=date(2026,11,21))
        self.assertEqual(out["new_price_stocks"],1)
        self.assertEqual(out["new_60_session_stocks"],0)
        self.assertEqual(out["stocks"][0]["new_valid_days"],1)
        self.assertFalse(out["price_existing_keys_overwritten"])
        fakeconn.cursor.return_value.__enter__.return_value.executemany.assert_called_once()
        state.assert_called_once()
        self.assertEqual(state.call_args.args[2],"success")

    def test_no_growth_is_visible_not_manufactured_coverage(self):
        fakeconn=MagicMock()
        fakeconn.__enter__.return_value=fakeconn
        stock={"market":"tpex","stock_id":"2330","valid_days":12,
               "newest":date(2026,11,20)}
        with patch.dict(os.environ,{"STOCK_TPEX_INSERT_ONLY_HISTORY_ENABLED":"yes"}),\
             patch.object(src.psycopg,"connect",return_value=fakeconn),\
             patch.object(src,"_size_guard",return_value=230000000),\
             patch.object(src,"select_candidates",return_value=[stock]),\
             patch.object(src,"fetch_verified_history",return_value=[]),\
             patch.object(src,"_count",side_effect=[12,12]),\
             patch.object(src,"_state") as state:
            out=src.run("fake",apply=True,limit=1,today=date(2026,11,21))
        self.assertEqual(out["no_growth"],1)
        self.assertEqual(out["new_price_stocks"],0)
        self.assertEqual(out["stocks"][0]["status"],"no_verified_new_prices")
        self.assertEqual(state.call_args.args[2],"failed")

    def test_bad_source_does_not_write_prices_and_reports_failed(self):
        fakeconn=MagicMock()
        fakeconn.__enter__.return_value=fakeconn
        stock={"market":"tpex","stock_id":"2330","valid_days":1,
               "newest":date(2026,11,20)}
        with patch.dict(os.environ,{"STOCK_TPEX_INSERT_ONLY_HISTORY_ENABLED":"yes"}),\
             patch.object(src.psycopg,"connect",return_value=fakeconn),\
             patch.object(src,"_size_guard",return_value=230000000),\
             patch.object(src,"select_candidates",return_value=[stock]),\
             patch.object(src,"fetch_verified_history",side_effect=ValueError("bad source")),\
             patch.object(src,"_state") as state:
            out=src.run("fake",apply=True,limit=1,today=date(2026,11,21))
        self.assertEqual(out["rejected"],1)
        fakeconn.cursor.return_value.__enter__.return_value.executemany.assert_not_called()
        self.assertEqual(state.call_args.args[2],"failed")


if __name__=="__main__":
    import unittest
    unittest.main()
