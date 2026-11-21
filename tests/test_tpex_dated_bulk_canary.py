"""Offline tests: no database credentials, exchange requests or state mutation."""
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from src import tpex_dated_bulk_canary as canary

FIELDS = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低",
          "成交股數", "成交金額(元)", "成交筆數"]


def fixture(day_code=0):
    rows = []
    for i in range(500):
        rows.append([str(1000+i), "TEST", str(20 + day_code), "0",
                     str(20 + day_code), str(21 + day_code),
                     str(19 + day_code), "1,000", "20,000", "10"])
    return {"stat": "ok", "tables": [{"fields": list(FIELDS), "data": rows}]}


class FakeResponse:
    def __init__(self, json_data):
        self.payload = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResponse(fixture(len(self.calls)))


class TPExDatedBulkCanaryTests(TestCase):
    def test_parses_500_quotes_without_approving_writes(self):
        result = canary.parse_day(fixture(), date(2026, 11, 18))
        self.assertEqual(result["valid_four_digit_codes"], 500)
        self.assertFalse(result["date_independently_verified"])
        self.assertFalse(result["write_approved"])

    def test_unknown_fields_and_bad_prices_fail_closed(self):
        bad = fixture()
        bad["tables"][0]["fields"][7] = "成交仟股"
        with self.assertRaisesRegex(ValueError, "Too few"):
            canary.parse_day(bad, date(2026, 11, 18))
        bad = fixture()
        bad["tables"][0]["data"][0][4] = "999"
        with self.assertRaisesRegex(ValueError, "OHLC"):
            canary.parse_day(bad, date(2026, 11, 18))

    def test_bounded_get_only_no_import(self):
        fake = FakeSession()
        result = canary.probe([date(2026, 11, 18), date(2026, 11, 19)], fake)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all(x[1]["params"]["type"] == "EW" for x in fake.calls))
        with self.assertRaisesRegex(ValueError, "one or two"):
            canary.probe([date(2026, 11, 18)] * 3, fake)
        self.assertEqual(len(fake.calls), 2)

    def test_identical_day_snapshots_rejected(self):
        class Same(FakeSession):
            def get(self, *args, **kwargs):
                return FakeResponse(fixture())
        with self.assertRaisesRegex(ValueError, "identical"):
            canary.probe([date(2026, 11, 18), date(2026, 11, 19)], Same())
