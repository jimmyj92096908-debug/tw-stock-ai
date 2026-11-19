"""Official daily market feed parser tests; no network or production DB."""
import unittest
from datetime import date
from decimal import Decimal

from src.official_market_feed import (
    numeric, official_date, _parse_twse, _parse_tpex,
    select_candidates, signed_twse_change, fetch_latest_snapshot,
)

FIELDS = [
    "證券代號","證券名稱","成交股數","成交筆數","成交金額",
    "開盤價","最高價","最低價","收盤價","漲跌(+/-)","漲跌價差"
]
DAY = date(2026,11,19)


def twse_payload(rows=None, title="115年11月19日 每日收盤行情"):
    return {"stat":"OK","tables":[{"title":title,"fields":FIELDS,"data":rows or [
        ["2330","台積電","1,000","10","1,400,000","1390","1410","1380","1400","<p style= color:green>-</p>","5"],
        ["006208","ETF","500","8","1000","60","61","59","60","<p>+</p>","1"],
        ["6213","樣本","0","0","0","--","--","--","--","X","--"]
    ]}]}


def tpex_payload():
    return [
        {"Date":"1151119","SecuritiesCompanyCode":"6488","CompanyName":"環球晶",
         "Open":"420","High":"430","Low":"415","Close":"425",
         "Change":"+5.00","TradingShares":"8000","TransactionAmount":"3400000","TransactionNumber":"40"},
        {"Date":"1151119","SecuritiesCompanyCode":"006201","Close":"20",
         "Open":"20","High":"20","Low":"20","Change":"0.0",
         "TradingShares":"100","TransactionAmount":"2000","TransactionNumber":"1"},
        {"Date":"1151119","SecuritiesCompanyCode":"12345A","Close":"20"}
    ]


class FakeResponse:
    def __init__(self,data):
        self.data=data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, response):
        self.response=response
        self.calls=[]

    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return FakeResponse(self.response)


class OfficialQuoteTests(unittest.TestCase):
    def test_known_official_roc_dates_and_bad_dates(self):
        self.assertEqual(official_date("1151119"), DAY)
        self.assertEqual(official_date("20261119"), DAY)
        self.assertEqual(official_date("115/11/19"), DAY)
        self.assertEqual(official_date("115年11月19日"),DAY)
        for bad in ("", "not-a-date", "1151332", "20260144"):
            with self.assertRaises(ValueError):
                official_date(bad)

    def test_parse_twse_real_field_names_and_sign(self):
        bars=_parse_twse(twse_payload(),DAY)
        self.assertEqual(len(bars),2)
        quote=next(row for row in bars if row["stock_id"]=="2330")
        self.assertEqual(quote["volume"],1000)
        self.assertEqual(quote["close"],Decimal("1400"))
        self.assertEqual(quote["price_change"],Decimal("-5"))
        self.assertEqual(quote["trade_date"],DAY)
        self.assertTrue(quote["source"].startswith("TWSE_"))
        only=select_candidates(bars,{("twse","2330")},minimum=1)
        self.assertEqual([x["stock_id"] for x in only],["2330"])

    def test_parse_tpex_real_keys_and_reject_etf_by_master_join(self):
        bars=_parse_tpex(tpex_payload(),DAY)
        self.assertEqual(len(bars),2)
        rows=select_candidates(bars,{("tpex","6488")},minimum=1)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["price_change"],Decimal("+5.00"))
        self.assertEqual(rows[0]["transactions"],40)

    def test_stale_or_mixed_dates_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"different trade date"):
            _parse_twse(twse_payload(title="115年11月18日 每日收盤行情"),DAY)
        wrong=tpex_payload()
        wrong[0]["Date"]="1151118"
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            _parse_tpex(wrong,DAY)
        with self.assertRaisesRegex(ValueError,"covered only"):
            select_candidates(_parse_twse(twse_payload(),DAY),{("twse","2330")},minimum=2)

    def test_numeric_bounds_nonfinite_and_close_outside_high(self):
        self.assertIsNone(numeric("--"))
        for bad in ("nan","Infinity","data"):
            with self.assertRaises(ValueError):
                numeric(bad)
        self.assertIsNone(signed_twse_change("X","5"))
        self.assertEqual(signed_twse_change("<p>+</p>","7"),Decimal("7"))
        row=["2330","台積電","1,000","10","1,400,000","1390","1399","1380","1400","+","5"]
        with self.assertRaisesRegex(ValueError,"no valid"):
            _parse_twse(twse_payload(rows=[row]),DAY)

    def test_fetch_single_date_twse_and_tpex(self):
        session=FakeSession(twse_payload())
        day,bars=fetch_latest_snapshot("twse",today=DAY,session=session)
        self.assertEqual(day,DAY)
        self.assertEqual(len(bars),2)
        self.assertEqual(session.calls[0][1]["params"]["date"],"20261119")
        session=FakeSession(tpex_payload())
        day,bars=fetch_latest_snapshot("tpex",today=DAY,session=session)
        self.assertEqual(day,DAY)
        self.assertEqual(len(bars),2)

    def test_duplicate_candidate_and_unknown_market_fail(self):
        bars=_parse_twse(twse_payload(),DAY)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            select_candidates([bars[0],bars[0]],{("twse","2330")},minimum=1)
        with self.assertRaises(ValueError):
            fetch_latest_snapshot("unknown",today=DAY,session=FakeSession({}))


if __name__ == "__main__":
    unittest.main()
