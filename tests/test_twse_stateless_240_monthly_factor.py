"""TWSE 13-month RAM-only 240-session SMA, technical and SMC safety tests."""
from datetime import date,timedelta
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import twse_stateless_240_monthly_factor as m


def days(month):
    t=month
    result=[]
    while t.month==month.month:
        if t.weekday()<5:
            result.append(t)
        t+=timedelta(days=1)
    return result[:20]


def monthly_bars(month, *, close_shift=0):
    result=[]
    for i,dt in enumerate(days(month)):
        n=(month.year-2021)*12+month.month
        close=Decimal("100.00")+Decimal(n*2+i)/Decimal("10")+Decimal(close_shift)
        result.append({
            "market":"twse","stock_id":"2330","trade_date":dt,
            "open":close,"high":close+Decimal("1.00"),
            "low":close-Decimal("1.00"),"close":close,
            "volume":1_000_000+i,"turnover":close*Decimal(1_000_000+i),
            "transactions":1234,"price_change":Decimal("0.1"),
            "source":"TWSE_STOCK_DAY",
        })
    return result


def payload(month, *, code="2330", bad_numeric=None):
    result=[]
    for row in monthly_bars(month):
        d=row["trade_date"]
        data=[
            f"{d.year-1911}/{d.month:02d}/{d.day:02d}",
            f"{row['volume']:,}","100,000,000",
            str(row["open"]),str(row["high"]),str(row["low"]),
            str(row["close"]),"+0.10","1,234","",
        ]
        if bad_numeric is not None:
            data[bad_numeric[0]]=bad_numeric[1]
        result.append(data)
    return {
        "stat":"OK","date":month.strftime("%Y%m%d"),
        "title":f"{month.year-1911}年{month.month:02d}月 2330 台積電 各日成交資訊",
        "fields":["日期","成交股數","成交金額","開盤價","最高價",
                  "最低價","收盤價","漲跌價差","成交筆數","註記"],
        "data":result,
    }


class MonthlyStateless240Tests(TestCase):
    def test_official_13_months_realistic_parser_exact_decimals(self):
        all_bars=[m.parse_month(payload(dt),month=dt) for dt in m.MONTHS]
        self.assertEqual(len(all_bars),13)
        self.assertGreater(sum(map(len,all_bars)),240)
        self.assertIs(type(all_bars[0][0]["close"]),Decimal)
        self.assertEqual(all_bars[0][0]["source"],"TWSE_STOCK_DAY")
        first=all_bars[0][0]
        self.assertEqual(first["market"],"twse")
        self.assertEqual(first["stock_id"],"2330")
        self.assertGreater(first["close"],0)

    def test_ma240_and_existing_technical_smc_causal_from_real_session_shapes(self):
        all_bars=[monthly_bars(dt) for dt in m.MONTHS]
        result=m.assess_months(all_bars)
        self.assertEqual(result["stock_count"],1)
        self.assertEqual(result["official_months_fetched"],13)
        self.assertGreater(result["actual_valid_stock_sessions"],240)
        self.assertEqual(result["feature_count"],12)
        self.assertTrue(result["exact_decimal_sma240_causal_parity_passed"])
        self.assertTrue(result["causal_previous_day_prefix_parity_passed"])
        self.assertTrue(result["actual_240_session_warmup_met"])
        self.assertFalse(result["all_market_240_day_coverage_proven"])
        self.assertFalse(result["dividend_adjusted_total_return_proven"])
        self.assertFalse(result["independent_future_model_validation_passed"])
        self.assertEqual(result["neon_derived_rows_written"],0)
        self.assertEqual(result["github_raw_market_price_artifacts"],0)
        self.assertFalse(result["model_live_trading_approved"])
        self.assertNotIn("stock_prices",result)
        self.assertNotIn("feature_vector",result)

        flat=[r for month in all_bars for r in month]
        actual=m.exact_sma240(flat,asof=flat[-1]["trade_date"])
        expect=sum((x["close"] for x in flat[-240:]),Decimal(0))/Decimal(240)
        self.assertEqual(actual,expect)
        previous=m.exact_sma240(flat,asof=flat[-2]["trade_date"])
        self.assertEqual(previous,m.exact_sma240(
            flat[:-1],asof=flat[-2]["trade_date"]))
        flat[-1]["close"]=Decimal("4000.0")
        self.assertEqual(previous,m.exact_sma240(flat,asof=flat[-2]["trade_date"]))

    def test_strict_bad_source_month_code_title_and_quotes(self):
        dt=m.MONTHS[0]
        for wrong in ("title","month","issuer","duplicate","bad_price","invalid_range",
                      "no_trade","nonfinite"):
            p=payload(dt)
            if wrong=="title":
                p["title"]=p["title"].replace("2330","2317")
            if wrong=="month":
                p["date"]="20261201"
            if wrong=="issuer":
                p["title"]=p["title"].replace("2330","1589")
            if wrong=="duplicate":
                p["data"][1]=p["data"][0]
            if wrong=="bad_price":
                p["data"][0][6]="-100"
            if wrong=="invalid_range":
                p["data"][0][4]="0.1"
            if wrong=="no_trade":
                p["data"]=[p["data"][0]]
                p["data"][0][6]="--"
            if wrong=="nonfinite":
                p["data"][0][6]="NaN"
            with self.subTest(wrong=wrong),self.assertRaises(ValueError):
                m.parse_month(p,month=dt)

    def test_insufficient_240_session_rejected(self):
        cases=[
            [monthly_bars(dt)[:18] for dt in m.MONTHS],
            [monthly_bars(dt) for dt in m.MONTHS][:-1],
        ]
        for bad in cases:
            with self.assertRaises(ValueError):
                m.assess_months(bad)
        flat=[r for dt in m.MONTHS for r in monthly_bars(dt)]
        with self.assertRaises(ValueError):
            m.exact_sma240(flat[:200],asof=flat[199]["trade_date"])

    def test_readonly_roster_13_month_request_budget_and_aggregates_only(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={"eligible":1}
        seen=[]
        def month_loader(month):
            seen.append(month)
            return monthly_bars(month)
        with (
            TemporaryDirectory() as tmp,
            patch("psycopg.connect",return_value=conn) as dial,
            patch.object(m.time,"sleep") as sleep,
        ):
            dest=Path(tmp)/"aggregate-only.json"
            report=m.execute("postgresql://fake",loader=month_loader,output=dest)
            self.assertEqual(seen,list(m.MONTHS))
            self.assertEqual(sleep.call_count,12)
            self.assertEqual(report["neon_derived_rows_written"],0)
            self.assertFalse(report["model_live_trading_approved"])
            data=dest.read_text()
            self.assertEqual(json.loads(data),report)
            self.assertNotIn("2330",data)
            self.assertNotIn("100.00",data)
            self.assertIn("default_transaction_read_only=on",
                          dial.call_args.kwargs["options"])
            self.assertEqual(conn.execute.call_args_list[0].args[0],
                             "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

    def test_missing_official_roster_refuses_http(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={"eligible":0}
        seen=[]
        with patch("psycopg.connect",return_value=conn):
            with self.assertRaisesRegex(ValueError,"not a fresh official"):
                m.execute("fake",loader=lambda x:seen.append(x))
        self.assertEqual(seen,[])

    def test_no_tainted_sql_and_fixed_monthly_request_bound(self):
        self.assertIn("official_current_listed",m.ROSTER_SQL)
        self.assertIn("model_stock_exclusions",m.ROSTER_SQL)
        for token in ("INSERT INTO","UPDATE ","DELETE FROM","TRUNCATE ","DROP "):
            self.assertNotIn(token,m.ROSTER_SQL.upper())
        self.assertEqual(m.MAX_SOURCE_REQUESTS,13)
        self.assertEqual(len(m.MONTHS),13)
        self.assertEqual(m.STOCK_ID,"2330")
        self.assertFalse("1589"==m.STOCK_ID)
