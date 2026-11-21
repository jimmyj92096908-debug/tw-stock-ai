"""Conservative zero-paid Neon budget guard, with explicit UNKNOWN network state.

Database size can be measured from PostgreSQL, but actual network egress and
compute units CANNOT be inferred from table size or pg_stat_database. Only
use Neon API consumption fields when a read-only API token is available.
Never print or save Neon credentials or DATABASE_URL.
"""
from __future__ import annotations

from datetime import datetime,timezone
import argparse,json,os
from pathlib import Path
from urllib.request import Request,urlopen

import psycopg
from psycopg.rows import dict_row

PROJECT_ID="royal-scene-68859981"
DB_STOP_BYTES=800_000_000
DB_WARN_BYTES=650_000_000
TRANSFER_LIMIT_BYTES=5_000_000_000
TRANSFER_WARN_BYTES=3_500_000_000
TRANSFER_PAUSE_BYTES=4_500_000_000
NEON_PROJECT_API="https://console.neon.tech/api/v2/projects/"+PROJECT_ID
SIZE_SQL="SELECT pg_database_size(current_database())::bigint AS bytes"

def assess(*,db_bytes,usage=None):
    if type(db_bytes) is not int or db_bytes<1:
        raise ValueError("Verified database bytes required")
    if db_bytes>=DB_STOP_BYTES:
        db_level="STOP"
    elif db_bytes>=DB_WARN_BYTES:
        db_level="WARNING"
    else:
        db_level="NORMAL"
    transfer=None
    transfer_state="UNAVAILABLE"
    compute_seconds=None
    period_end=None
    if usage is not None:
        if not isinstance(usage,dict) or usage.get("id")!=PROJECT_ID:
            raise ValueError("Neon usage project identity mismatch")
        t=usage.get("data_transfer_bytes")
        if type(t) is not int or t<0:
            raise ValueError("Neon transfer counter is not verified")
        transfer=t
        compute_seconds=usage.get("compute_time_seconds")
        if type(compute_seconds) is not int or compute_seconds<0:
            raise ValueError("Invalid Neon compute counter")
        period_end=usage.get("consumption_period_end")
        if not isinstance(period_end,str) or not period_end:
            raise ValueError("Unknown consumption billing window")
        transfer_state=(
            "PAUSE_NEW_NONESSENTIAL_WORK" if t>=TRANSFER_PAUSE_BYTES
            else "WARNING" if t>=TRANSFER_WARN_BYTES else "NORMAL"
        )
    can_expand=bool(db_level!="STOP" and transfer is not None
                    and transfer_state!="PAUSE_NEW_NONESSENTIAL_WORK")
    return {
        "schema_version":1,"scope":"NEON_FREE_BUDGET_FAIL_CLOSED",
        "neon_project_id":PROJECT_ID,
        "database_bytes":db_bytes,"database_stop_bytes":DB_STOP_BYTES,
        "database_warning_bytes":DB_WARN_BYTES,"database_status":db_level,
        "project_network_transfer_bytes":transfer,
        "project_network_limit_assumption_bytes":TRANSFER_LIMIT_BYTES,
        "network_warning_bytes":TRANSFER_WARN_BYTES,
        "network_pause_new_jobs_bytes":TRANSFER_PAUSE_BYTES,
        "network_transfer_status":transfer_state,
        "neon_usage_period_end":period_end,
        "reported_compute_time_seconds":compute_seconds,
        "compute_CU_hours_derived_without_compute_size":False,
        "network_unknown_is_never_reported_safe":True,
        "additional_data_intensive_jobs_authorized":can_expand,
        "paid_upgrade_authorized":False,
        "database_writes":0,
        "LINE_or_trading_enabled":False,
    }

def fetch_meter(token,*,url=NEON_PROJECT_API,opener=urlopen):
    if not token:
        return None
    if url!=NEON_PROJECT_API:
        raise ValueError("Only fixed trusted Neon project endpoint is allowed")
    request=Request(url,headers={
        "Authorization":"Bearer "+token,"Accept":"application/json",
        "User-Agent":"tw-stock-ai/free-budget-readonly"})
    with opener(request,timeout=12) as response:
        payload=json.load(response)
    if not isinstance(payload,dict):
        raise ValueError("Invalid Neon project response")
    obj=payload.get("project")
    if not isinstance(obj,dict):
        raise ValueError("Expected exact Neon API project object")
    return obj

def run(url,token=None,*,report_path=None,require_network=False):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='20000ms'")
        size=conn.execute(SIZE_SQL).fetchone()["bytes"]
    api_error=None
    usage=None
    if token:
        try:
            usage=fetch_meter(token)
        except Exception as exc:
            # Redact arbitrary error strings: HTTP library could include URL
            # or future private metadata. Do not log tokens or exception text.
            api_error=type(exc).__name__
    report=assess(db_bytes=size,usage=usage)
    report["checked_at_utc"]=datetime.now(timezone.utc).isoformat()
    report["network_meter_error_type"]=api_error
    report["network_api_credential_configured"]=bool(token)
    report["mandatory_transfer_gate_passed"]=bool(
        report["additional_data_intensive_jobs_authorized"])
    if report_path:
        target=Path(report_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                          encoding="utf-8")
    if require_network and not report["mandatory_transfer_gate_passed"]:
        raise RuntimeError("Conservative Free Network/Storage gate unavailable or exceeded")
    return report

def main():
    ap=argparse.ArgumentParser(description="Read-only size + honest Neon Free network counter gate")
    ap.add_argument("--report",type=Path,default=Path("neon-free-meter.json"))
    ap.add_argument("--require-network",action="store_true")
    a=ap.parse_args()
    report=run(os.getenv("DATABASE_URL",""),os.getenv("NEON_API_KEY",""),
               report_path=a.report,require_network=a.require_network)
    print(json.dumps({k:report[k] for k in (
        "database_bytes","database_status","project_network_transfer_bytes",
        "network_transfer_status","network_api_credential_configured",
        "additional_data_intensive_jobs_authorized","database_writes")},
        ensure_ascii=False))
if __name__=="__main__":
    main()
