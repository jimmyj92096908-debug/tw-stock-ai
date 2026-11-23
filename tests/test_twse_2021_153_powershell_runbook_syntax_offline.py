"""Offline guard for PR244 owner PowerShell 5.1 evidence runbook syntax.

This checks the actual documentation excerpt; it is deliberately not an
assertion that Linux Python can execute Windows PowerShell.
"""
from pathlib import Path
import re
import unittest

DOC = (Path(__file__).resolve().parents[1] /
       "docs/twse-2021-153-zero-source-official-current-listing-triage.md")


class Owner2021ListingTriagePowerShellRunbookTests(unittest.TestCase):
    def test_2021_owner_runbook_avoids_invalid_numeric_leading_output_keys(self):
        doc=DOC.read_text(encoding="utf-8")
        self.assertIn("## Windows PowerShell 5.1 執行方式",doc)
        code=doc.split("```powershell",1)[1].split("```",1)[0]
        self.assertTrue(code.lstrip().startswith("& {"))
        self.assertTrue(code.rstrip().endswith("}"))
        self.assertEqual(code.count("{"),code.count("}"))
        self.assertNotRegex(
            code,re.compile(r"(?m)^\s*[0-9]+[^\s'=]+\s*="),
        )
        self.assertIn("Write-Host",code)
        self.assertIn("current_listing_year_and_period_bucket_counts",code)
        self.assertIn("TWSE_KEY_GUI_PROMPT",code)
        self.assertIn("if (Test-Path $output)",code)
        self.assertIn("--prior-243-union-report",code)

    def test_returned_proof_checked_before_displaying_counts(self):
        doc=DOC.read_text(encoding="utf-8")
        code=doc.split("```powershell",1)[1].split("```",1)[0]
        self.assertIn("OWNER_2021_TWSE_153_ZERO_SOURCE_CURRENT_OFFICIAL_LISTING_DATE_TRIAGE",code)
        self.assertIn("$r.no_2021_aes_or_neon_source_issuer_count -ne 153",code)
        self.assertIn("$r.model_release -ne 'BLOCKED'",code)
        self.assertLess(code.index("throw '新報告驗收欄位不符"),code.index("Write-Host"))


if __name__=="__main__":
    unittest.main()
