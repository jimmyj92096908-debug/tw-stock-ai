"""No-network safety tests for bounded enrichment of sparse daily snapshots."""
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from src import bounded_history_enrichment as enrichment


class FakeCursor:
    def __init__(self):
        self.sql = None
        self.params = None
        self.calls = []
        self.check_row = {"price_days":58,"min_day":date(2026,8,1),
                          "max_day":date(2026,11,19)}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params
        self.calls.append((sql,params))
        if sql != enrichment.CHECK_SQL:
            assert sql.strip().upper().startswith(("SELECT","WITH"))

    def fetchall(self):
        if self.params[0] == "twse":
            return [{
                "market":"twse","stock_id":"1101","stock_name":"mock",
                "earliest_trade_date":date(2026,11,19),
                "latest_trade_date":date(2026,11,19),"price_days":1
            }]
        return [{
            "market":"tpex","stock_id":"1259","stock_name":"mock",
            "earliest_trade_date":date(2026,11,19),
            "latest_trade_date":date(2026,11,19),"price_days":1
        }]

    def fetchone(self):
        return self.check_row


class FakeConnection:
    def __init__(self):
        self.cur=FakeCursor()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def cursor(self):
        return self.cur


class BoundedHistoryTests(TestCase):
    def test_rejects_unsafe_market_batches_and_missing_write_permission(self):
        fake=FakeConnection()
        for n in (0,3,100,-1):
            with self.assertRaisesRegex(ValueError,"Only 1 or 2"):
                enrichment.execute("fake",apply=False,per_market=n)
        with self.assertRaisesRegex(ValueError,"opt-in gate"):
            enrichment.execute("fake",apply=True)
        with self.assertRaisesRegex(ValueError,"Unsafe market"):
            enrichment.select_candidates(fake,"other",1)
        self.assertIn("sm.stock_id<>'1808'",enrichment.CANDIDATES_SQL)
        self.assertIn("priced.price_days BETWEEN 1 AND 59",enrichment.CANDIDATES_SQL)

    def test_dry_run_does_not_download_or_touch_database(self):
        fake=FakeConnection()
        with (
            patch.object(enrichment.psycopg,"connect",return_value=fake),
            patch.object(enrichment,"refresh_one",side_effect=AssertionError("unexpected download")),
        ):
            out=enrichment.execute("postgresql://dummy",today=date(2026,11,20))
        self.assertEqual(len(out),2)
        self.assertEqual([x["status"] for x in out],["dry-run","dry-run"])
        self.assertTrue(all(x["months_requested"]<=5 for x in out))
        self.assertEqual(len(fake.cur.calls),2)
        self.assertEqual([x[1] for x in fake.cur.calls],[("twse",2),("tpex",2)])

    def test_apply_requires_gate_and_checks_new_history_and_indicators(self):
        fake=FakeConnection()
        with (
            patch.dict(enrichment.os.environ,{"STOCK_ENRICHMENT_WRITE_ENABLED":"yes"}),
            patch.object(enrichment.psycopg,"connect",return_value=fake),
            patch.object(enrichment,"refresh_one",return_value=None) as refresh,
            patch.object(enrichment,"build_adjusted_stock",return_value=58),
            patch.object(enrichment,"calculate_technical_stock",return_value=58),
            patch.object(enrichment,"calculate_smc_stock",return_value=58),
        ):
            out=enrichment.execute("fake",apply=True,today=date(2026,11,20),
                                   per_market=1,pause_seconds=0)
        self.assertEqual(refresh.call_count,2)
        self.assertEqual([x["status"] for x in out],["verified","verified"])
        self.assertEqual([x["price_days"] for x in out],[58,58])

    def test_one_failure_is_reported_without_leaking_error_details(self):
        fake=FakeConnection()
        with (
            patch.dict(enrichment.os.environ,{"STOCK_ENRICHMENT_WRITE_ENABLED":"yes"}),
            patch.object(enrichment.psycopg,"connect",return_value=fake),
            patch.object(enrichment,"refresh_one",side_effect=Exception("SECRET-DB-PASSWORD")),
            patch.object(enrichment,"build_adjusted_stock",side_effect=AssertionError("unreachable")),
        ):
            with self.assertLogs(enrichment.LOGGER,level="ERROR") as logs:
                out=enrichment.execute("fake",apply=True,today=date(2026,11,20),
                                       per_market=1,pause_seconds=0)
        self.assertEqual([x["status"] for x in out],["failed","failed"])
        self.assertTrue(all(x["error_type"]=="Exception" for x in out))
        self.assertNotIn("SECRET-DB-PASSWORD","\n".join(logs.output))

    def test_recent_sparse_stock_downloads_contiguous_july_to_november(self):
        for earliest in (date(2026,9,20),date(2026,10,27),
                         date(2026,10,30),date(2026,11,19)):
            with self.subTest(earliest=earliest):
                stock={
                    "earliest_trade_date":earliest,
                    "latest_trade_date":date(2026,11,20),
                }
                windows=enrichment.plan_bounded_windows(stock,date(2026,11,21))
                self.assertEqual(windows,[
                    (date(2026,7,1),date(2026,11,1))
                ])
                self.assertEqual(enrichment.count_months(windows),5)
        # This change does not broaden the ordinary older-stock rotation.
        old={"earliest_trade_date":date(2026,4,28),
             "latest_trade_date":date(2026,11,20)}
        self.assertEqual(
            enrichment.plan_bounded_windows(old,date(2026,11,21)),
            enrichment.plan_download_windows(old,date(2026,11,21))
        )

    def test_no_growth_is_not_falsely_reported_as_verified(self):
        fake=FakeConnection()
        fake.cur.check_row={
            "price_days":1,"min_day":date(2026,11,19),
            "max_day":date(2026,11,19)
        }
        with (
            patch.dict(enrichment.os.environ,{"STOCK_ENRICHMENT_WRITE_ENABLED":"yes"}),
            patch.object(enrichment.psycopg,"connect",return_value=fake),
            patch.object(enrichment,"refresh_one",return_value=True) as refresh,
            patch.object(enrichment,"build_adjusted_stock",
                         side_effect=AssertionError("no growth means no indicator rewrites")),
            patch.object(enrichment,"calculate_technical_stock",
                         side_effect=AssertionError("no growth means no technical rewrites")),
            patch.object(enrichment,"calculate_smc_stock",
                         side_effect=AssertionError("no growth means no SMC rewrites")),
        ):
            out=enrichment.execute(
                "fake",apply=True,today=date(2026,11,20),per_market=1,pause_seconds=0
            )
        self.assertEqual([r["status"] for r in out],["no-growth","no-growth"])
        self.assertEqual(refresh.call_count,2)
        self.assertEqual(out[0]["price_days"],1)
        self.assertNotIn("technical_rows",out[0])
        for call in refresh.call_args_list:
            self.assertEqual(enrichment.count_months(call.kwargs["windows"]),5)

    def test_real_regression_still_fails_and_does_not_become_no_growth(self):
        self.assertEqual(enrichment.classify_enrichment_growth(
            16,date(2026,11,20),
            {"price_days":16,"max_day":date(2026,11,20)}
        ),"no-growth")
        self.assertEqual(enrichment.classify_enrichment_growth(
            16,date(2026,11,20),
            {"price_days":20,"max_day":date(2026,11,20)}
        ),"new-history")
        for count,latest in ((15,date(2026,11,20)),(16,date(2026,11,19))):
            with self.subTest(count=count,latest=latest):
                with self.assertRaisesRegex(RuntimeError,"regressed"):
                    enrichment.classify_enrichment_growth(
                        16,date(2026,11,20),
                        {"price_days":count,"max_day":latest}
                    )

    def test_source_month_cap_never_allows_unbounded_range(self):
        window=[(date(2026,1,1),date(2026,6,1))]
        self.assertEqual(enrichment.count_months(window),6)
        with (
            patch.object(enrichment.psycopg,"connect",return_value=FakeConnection()),
            patch.object(enrichment,"plan_bounded_windows",return_value=window),
        ):
            with self.assertRaisesRegex(ValueError,"window exceeded"):
                enrichment.execute("fake",today=date(2026,11,20))
