import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from scripts import owner_twse_direct_monthly_five_stock as m
from tests.test_owner_twse_direct_monthly_source_canary import raw

class ExpansionTests(unittest.TestCase):
    def test_frozen_selection(self):
        groups={("twse",d):["1101","2330","2317","2308","2454","2881","2882"]
                for d in m.m.DATES}
        ids=m.select(groups)
        self.assertEqual(len(ids),5)
        self.assertTrue(set(m.c.STOCKS)<=set(ids))
        self.assertEqual(ids,m.select(groups))
        self.assertEqual(len(m.queue_for(ids,2023,1)),15)
        self.assertEqual(len(m.queue_for(ids,2026,4)),10)
        with self.assertRaises(ValueError):
            m.queue_for(ids,2027,1)

    def test_original_cache_reuse(self):
        groups={("twse",d):["1101","2330","2317","2308","2454"] for d in m.m.DATES}
        # A date in March also falls on a weekday for this fixture.
        with TemporaryDirectory() as d, patch.object(m.chip,"verify_input",return_value=groups):
            with patch.object(m.c,"fetch",side_effect=lambda s,month,**kw:raw(s,month)):
                m.c.capture(d,get=None,sleeper=lambda _:None)
                r=m.run({},d,2023,1,get=None,sleeper=lambda _:None)
                self.assertEqual(r["reused_months"],4)
                self.assertEqual(r["new_official_requests"],11)
                self.assertEqual(r["verified_format_issuer_months"],15)
                r2=m.run({},d,2023,1,get=None,sleeper=lambda _:None)
                self.assertEqual(r2["new_official_requests"],0)
