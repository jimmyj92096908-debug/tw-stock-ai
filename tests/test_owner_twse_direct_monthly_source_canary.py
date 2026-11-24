import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from scripts import owner_twse_direct_monthly_source_canary as m

def raw(stock,month):
    y,mm=month.split("-")
    return json.dumps({"stat":"OK","title":stock+" stock","fields":list(m.FIELDS),
        "data":[[f"{int(y)-1911}/{mm}/03","1,000","100,000","100","101","99","100"]]},
        ensure_ascii=False).encode()

class CaptureTests(unittest.TestCase):
    def test_parse_and_tamper(self):
        r=m.parse_month(raw("2330","2023-01"),"2330","2023-01")
        self.assertEqual(r[0]["volume"],1000)
        self.assertEqual(r[0]["trade_date"],"2023-01-03")
        for value in (raw("1101","2023-01"),raw("2330","2023-02"),b'{"stat":"NO"}'):
            with self.assertRaises(ValueError):m.parse_month(value,"2330","2023-01")
        body=json.loads(raw("2330","2023-01"));body["data"].append(body["data"][0])
        with self.assertRaises(ValueError):m.parse_month(json.dumps(body).encode(),"2330","2023-01")

    def test_cache_restart_and_integrity(self):
        with TemporaryDirectory() as d:
            with patch.object(m,"fetch",side_effect=lambda stock,month,**kw:raw(stock,month)) as f:
                r=m.capture(d,get=None,sleeper=lambda _:None)
                self.assertEqual(r["new_official_requests"],4)
                self.assertEqual(r["valid_source_rows"],4)
                r=m.capture(d,get=None,sleeper=lambda _:None)
                self.assertEqual(r["new_official_requests"],0)
                self.assertEqual(r["reused_months"],4)
                self.assertEqual(f.call_count,4)
                p=Path(d)/"twse-stock-day-2330-2023-01.response.json"
                p.write_bytes(p.read_bytes()+b" ")
                with self.assertRaises(ValueError):m.capture(d,get=None,sleeper=lambda _:None)
                self.assertEqual(f.call_count,4)
