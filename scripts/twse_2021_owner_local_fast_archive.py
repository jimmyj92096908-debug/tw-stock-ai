"""One owner-PC command safely archives outstanding 2021 TWSE dates locally.

Restartable: authenticates all existing private AES archives in the supplied
owner-controlled directory *before* planning and skips already verified source
sessions. An interrupted run preserves completed AES files without overwriting.
Monthly source batches are <=8 actual 2330-backed exchange dates. No public
GitHub upload, production PostgreSQL writes, LINE, fees or trading release.

Only use on the owner's computer with existing encrypted key vault and
independently protected local archive folder; secrets never leave process RAM.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from scripts.twse_2021_remaining_26_official_source_audit import (
    ALL_DAYS as REMAINING_26,
)
from scripts.twse_2021_two_day_official_source_canary import (
    FROZEN_DAYS as PREVIOUS_TWO,
)
from scripts.twse_2021_22_archive_plan_readonly import rolling_start
from scripts.twse_archive_key_vault import resolve_archive_key
from scripts.twse_local_aes_gap_dedup import authenticated_archive_days
from scripts.twse_local_encrypted_archive import _key
from scripts.twse_official_direct_archive import (
    preflight,prepare_official_archive,
)
from src.twse_dated_history import fetch_official_day

ALL_2021_DAYS = tuple(sorted((*REMAINING_26,*PREVIOUS_TWO)))
MAX_LOCAL_DAYS = 28
MAX_DAYS_PER_BATCH = 8
MAX_SOURCE_GETS = 28
INTER_REQUEST_PAUSE = 4.0


def plan_private_batches(covered, *, today:date):
    """Pure fail-closed partition; never re-fetch verified local source days."""
    if (type(today) is not date or not isinstance(covered,(set,frozenset))
            or len(ALL_2021_DAYS)!=MAX_LOCAL_DAYS
            or tuple(sorted(set(ALL_2021_DAYS)))!=ALL_2021_DAYS
            or any(type(d) is not date or d.year!=2021 or d.weekday()>=5
                   for d in ALL_2021_DAYS)
            or any(type(d) is not date for d in covered)):
        raise ValueError("Exact 28-day 2021 source and authenticated local dates required")
    begin=rolling_start(today)
    eligible=tuple(d for d in ALL_2021_DAYS if begin<=d<today)
    if not eligible or not set(covered)<=set(eligible):
        raise ValueError("No eligible rolling-five-year source days or foreign AES dates")
    groups=[]
    current=[]
    for d in eligible:
        if d in covered:
            if current:
                groups.append(tuple(current))
                current=[]
            continue
        if current and (len(current)>=MAX_DAYS_PER_BATCH
                        or current[-1].month!=d.month):
            groups.append(tuple(current))
            current=[]
        current.append(d)
    if current:
        groups.append(tuple(current))
    if (any(len(batch)>MAX_DAYS_PER_BATCH or
            batch[0].year!=batch[-1].year or
            batch[0].month!=batch[-1].month or
            (batch[-1]-batch[0]).days>35 for batch in groups)
            or sum(map(len,groups))+len(covered)!=len(eligible)):
        raise RuntimeError("Source-day re-fetch suppression or batch bounds invalid")
    return tuple(groups),len(eligible)


def _private_dir(path):
    original=Path(path).expanduser()
    if original.is_symlink() or not original.is_dir():
        raise ValueError("A real existing owner-private folder is required")
    final=original.resolve()
    if any((parent/".git").exists() for parent in (final,*final.parents)):
        raise ValueError("Never save an AES source inside a Git repository")
    return final


def run_local(database_url,*,archive_dir,hex_key,today=None,
              fetcher=fetch_official_day,sleeper=time.sleep,
              prepare=prepare_official_archive,
              preflight_fn=preflight,
              existing_day_validator=authenticated_archive_days):
    """Local encrypted writes only; no database mutations or remote uploads."""
    _key(hex_key)
    today=today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    if not database_url or not callable(fetcher) or not callable(sleeper):
        raise ValueError("Protected readonly Neon and official source access required")
    dest=_private_dir(archive_dir)
    existing_files=sorted(dest.glob("*.twseenc"))
    start=rolling_start(today)
    end=min(today,date(2022,1,1))
    if start>=end:
        raise ValueError("No eligible rolling-five-year 2021 source window")
    if existing_files:
        verified=existing_day_validator(existing_files,hex_key=hex_key,
                                       start=start,end=end)
        if verified.get("full_file_integrity_verified") is not True:
            raise ValueError("Unverified owner AES source folder cannot be reused")
        covered=verified["days"]
    else:
        covered=frozenset()
    batches,eligible=plan_private_batches(covered,today=today)
    planned_days=tuple(d for batch in batches for d in batch)
    request_count=0
    written=0
    saved_rows=0
    manifests=0
    for batch in batches:
        if len(batch)>MAX_DAYS_PER_BATCH:
            raise RuntimeError("Unsafe source batch limit")
        actual,allowed=preflight_fn(database_url,start=batch[0],
                                    end=batch[-1],today=today)
        if tuple(actual)!=batch or len(allowed)<700 or ("twse","1589") in allowed:
            raise ValueError("Live Neon official survivor source scope has changed")
        archive=dest/f"twse-2021-{batch[0]:%Y%m%d}-{batch[-1]:%Y%m%d}.twseenc"
        manifest=dest/f"twse-2021-{batch[0]:%Y%m%d}-{batch[-1]:%Y%m%d}.manifest.json"
        if archive.exists() or manifest.exists():
            raise FileExistsError("Preexisting unverified private batch output may not be overwritten")
        def paced(day):
            nonlocal request_count
            if (request_count>=MAX_SOURCE_GETS
                    or day!=planned_days[request_count]):
                raise RuntimeError("Unexpected source date or over-budget official GET")
            if request_count:
                sleeper(INTER_REQUEST_PAUSE)
            request_count+=1
            return fetcher(day)
        report=prepare(
            database_url,start=batch[0],end=batch[-1],
            archive_path=archive,manifest_path=manifest,
            object_key=(
                f"market=twse/year=2021/"
                f"twse-2021-{batch[0]:%Y%m%d}-{batch[-1]:%Y%m%d}.twseenc"
            ),hex_key=hex_key,fetcher=paced,today=today)
        if (report["actual_official_session_dates"]!=
                [d.isoformat() for d in batch]
                or type(report["encrypted_source_rows"]) is not int
                or report["encrypted_source_rows"]<500*len(batch)
                or report["production_postgres_rows_written"]!=0
                or report["line_messages_sent"]!=0):
            raise RuntimeError("Local source archive receipt or no-write proof changed")
        written+=len(batch)
        saved_rows+=report["encrypted_source_rows"]
        manifests+=1
    if request_count!=len(planned_days) or written!=len(planned_days):
        raise RuntimeError("Not all originally planned source days were archived")
    return {
        "scope":"OWNER_PC_RESTARTABLE_2021_OFFICIAL_AES_LOCAL_ONLY",
        "eligible_known_2021_neon_2330_anchor_days":eligible,
        "existing_2021_private_aes_days_authenticated":len(covered),
        "new_2021_source_days_encrypted_this_run":written,
        "new_encrypted_official_source_rows":saved_rows,
        "new_local_aes_and_manifest_pairs":manifests,
        "new_source_requests_with_four_second_pacing":request_count,
        "remaining_unarchived_known_2021_source_days":eligible-len(covered)-written,
        "locally_authenticated_existing_source_files":len(existing_files),
        "neon_source_and_derived_rows_written":0,
        "neon_existing_data_deleted":0,
        "line_messages_sent":0,
        "paid_services_requested":False,
        "independent_offsite_backup_verified":False,
        "historical_asof_survivorship_bias_resolved":False,
        "total_return_corporate_actions_validated":False,
        "live_model_release_approved":False,
    }


def main():
    parser=argparse.ArgumentParser(
        description="Owner PC: 2021 official TWSE -> restartable private AES source archive")
    parser.add_argument("--archive-dir",required=True)
    parser.add_argument("--key-vault",required=True)
    cli=parser.parse_args()
    secret=resolve_archive_key(
        vault_path=Path(cli.key_vault),
        env_key=os.environ.get("STOCK_ARCHIVE_KEY_HEX",""),
    )
    try:
        receipt=run_local(
            os.environ.get("DATABASE_URL",""),
            archive_dir=Path(cli.archive_dir),hex_key=secret,
        )
    except Exception:
        # No raw provider URL, archive location or secret may go to shared logs.
        raise SystemExit("Private local 2021 AES archival incomplete; Neon untouched") from None
    print(json.dumps(receipt,ensure_ascii=False,allow_nan=False,sort_keys=True))


if __name__=="__main__":
    main()
