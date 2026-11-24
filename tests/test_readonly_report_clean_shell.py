"""Execute the same direct entrypoints that failed in scheduled workflows.

Real child processes, without any inherited Neon/LINE secrets or PYTHONPATH.
The clean-shell contract is independent of the implementation's import strategy.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def execute(*args, cwd=ROOT):
    # A small allowlist avoids inheriting any production credential.
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE",
                    "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LD_LIBRARY_PATH")}
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd,
                          env=env, capture_output=True, text=True, timeout=40)


class CleanShellReadOnlyReportTests(unittest.TestCase):
    def test_quality_monitor_package_unittest_without_pythonpath(self):
        result = execute("-m", "unittest", "tests.test_stock_db_audit", "-v")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])

    def test_direct_audit_and_rank_help_from_external_workdir(self):
        with tempfile.TemporaryDirectory() as directory:
            for args, expected in (
                ((ROOT/"src"/"stock_db_audit.py", "--help"), "--json"),
                ((ROOT/"scripts"/"trained_factor_pipeline.py", "rank", "--help"), "--model-in"),
            ):
                for _ in range(2):
                    result = execute(*args, cwd=directory)
                    self.assertEqual(result.returncode, 0, result.stderr[-3000:])
                    self.assertIn(expected, result.stdout)

    def test_missing_database_blocks_real_audit_and_rank_no_fake_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"ranking.json"
            cases = (
                (ROOT/"src"/"stock_db_audit.py", "--json"),
                (ROOT/"scripts"/"trained_factor_pipeline.py", "rank",
                 "--model-in", ROOT/"models"/"tw-factor-ridge-1-research.json",
                 "--output", output, "--limit", "10"),
            )
            for args in cases:
                result = execute(*args, cwd=directory)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DATABASE_URL", result.stderr)
                self.assertNotIn("ModuleNotFoundError", result.stderr)
                self.assertEqual(result.stdout.strip(), "")
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
