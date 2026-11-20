"""Record actual offline verification outcomes without storing test output or secrets."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SUITES = {
    "python": [("python-unit", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])],
    "line": [
        ("line-tests-and-isolated-postgres", ["npm", "test"]),
        ("line-bundle", ["npm", "run", "bundle"]),
        ("candidate-bundle", ["npm", "run", "bundle:candidate"]),
        ("candidate-fail-closed", ["node", "--input-type=module", "-e",
          "import c from './candidate-dist/index.mjs'; const r=await c.fetch(new Request('https://example.invalid/webhook',{method:'POST',body:JSON.stringify({events:[]})})); if(r.status!==503)process.exit(1);"]),
    ],
}

def run(suite, root, output, timeout):
    workdir = root / "line-stock-analysis" if suite == "line" else root
    checks = []
    for name, command in SUITES[suite]:
        start = time.monotonic()
        try:
            # Never save raw stdout/stderr: tests could accidentally log sensitive content.
            completed = subprocess.run(command, cwd=workdir, capture_output=True, timeout=timeout, check=False)
            status, code = ("passed" if completed.returncode == 0 else "failed"), completed.returncode
        except subprocess.TimeoutExpired:
            status, code = "timeout", None
        except OSError:
            status, code = "unavailable", None
        checks.append({"check": name, "status": status, "exit_code": code,
                       "duration_seconds": round(time.monotonic()-start, 2)})
        print(f"{name}: {status}", flush=True)
    passed = all(item["status"] == "passed" for item in checks)
    evidence = {
        "schema_version": 1, "suite": suite,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "runner_outcome": "passed" if passed else "failed", "checks": checks,
        "scope": "offline checks only; integration uses disposable PostgreSQL",
        "not_verified": ["real LINE end-to-end delivery", "production webhook cutover",
                         "production credentials or live Neon data"],
        "production_ready": False
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0 if passed else 1

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--suite", choices=sorted(SUITES), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=240)
    args = p.parse_args()
    raise SystemExit(run(args.suite, Path(__file__).resolve().parents[1], args.output, args.timeout))
