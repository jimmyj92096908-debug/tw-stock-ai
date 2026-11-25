import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts import owner_twse_five_stock_cache_audit_offline as a
from scripts import owner_twse_direct_monthly_source_canary as c
from tests.test_owner_twse_direct_monthly_source_canary import raw

class AuditTests(unittest.TestCase):
    def test_missing_partial_valid(self):
        ids=("1101","2308","2317","2330","2454")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(a.audit(ids,d)["status_counts"],{"MISSING":235})
            with patch.object(c,"fetch",side_effect=lambda s,m,**kw:raw(s,m)):
                c.capture(d,get=None,sleeper=lambda _:None)
            r=a.audit(ids,d)
            self.assertEqual(r["valid_months"],4)
            self.assertTrue(r["safe_to_resume_missing_only"])
            (Path(d)/"twse-stock-day-1101-2023-01.receipt.json").unlink()
            r=a.audit(ids,d)
            self.assertEqual(r["status_counts"]["INCOMPLETE_PAIR"],1)
            self.assertFalse(r["safe_to_resume_missing_only"])

    def test_safe_diagnostic(self):
        with tempfile.TemporaryDirectory() as d, patch.object(c,"fetch",side_effect=ValueError("private detail")):
            with self.assertRaises(c.CaptureFailure) as caught:
                c.capture(d,get=None,sleeper=lambda _:None)
            r=caught.exception.diagnostic()
            self.assertEqual(r["stage"],"OFFICIAL_HTTP")
            self.assertEqual(r["month"],"2023-01")
            self.assertNotIn("private detail",str(r))
