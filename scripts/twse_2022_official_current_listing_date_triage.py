"""Current TWSE issuer '上市日期' metadata, owner 129 no-2022-source triage.

Only official public TWSE OpenAPI, no company address/contact/name emitted.
The LIVE current basic-company snapshot is not historic point-in-time issuer
membership. The reported current TWSE listing date may reflect OTC-to-TWSE
transfer, relisting, or other changes. Never assume date == IPO / first-ever
tradable listing or justify filling/ignoring 2022 OHLCV without further proof.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
MAX_SOURCE_BYTES = 8_000_000
MAX_OFFICIAL_RECORDS = 2_000
MIN_OFFICIAL_RECORDS = 750


def _roc_snapshot_day(value: str) -> date:
    if not isinstance(value,str) or not re.fullmatch(r"\d{7}", value):
        raise ValueError("TWSE company metadata requires 7-digit ROC observation date")
    year = int(value[:3]) + 1911
    try:
        return date(year,int(value[3:5]),int(value[5:7]))
    except ValueError as exc:
        raise ValueError("Invalid official company publication date") from exc


def _listing_day(value):
    if value in ("", None, "—", "-", "－", " "):
        return None
    if not isinstance(value,str) or not re.fullmatch(r"(19|20)\d{6}",value):
        return None
    try:
        day = date(int(value[:4]),int(value[4:6]),int(value[6:8]))
    except ValueError:
        return None
    return day if day>=date(1961,1,1) else None


def fetch_official_company_basics(*, get=None):
    """One official HTTPS request. Full payload only in owner-process memory."""
    if get is None:
        import requests
        get=requests.get
    resp=get(URL, timeout=(8,35),headers={
        "Accept":"application/json",
        "User-Agent":"tw-stock-ai-free-current-listing-date-owner-audit",
    })
    resp.raise_for_status()
    target=urlparse(resp.url)
    if (target.scheme!="https"
            or target.hostname!="openapi.twse.com.tw"):
        raise ValueError("Current issuer listing data redirected off verified TWSE")
    data=resp.content
    if not isinstance(data,bytes) or not 0<len(data)<=MAX_SOURCE_BYTES:
        raise ValueError("Official current-company basics response size invalid")
    body=resp.json()
    if not isinstance(body,list) or not MIN_OFFICIAL_RECORDS<=len(body)<=MAX_OFFICIAL_RECORDS:
        raise ValueError("Missing or excessive official current-company issuer rows")
    return {"rows":body,"response_sha256":sha256(data).hexdigest(),
            "endpoint":URL}


def classify_official_current_listing(
        evidence, *, eligible_ids, no_2022_ids, first_2023plus,
        current_day, prior_window_end):
    """Validate source metadata and reconcile 129 missing source issuer IDs.

    Only summary buckets leave this function; no ticker IDs, raw names, prices,
    private Neon data, dates of individual issuers, contacts or credentials.
    """
    if (not isinstance(evidence,dict)
            or evidence.get("endpoint")!=URL
            or not isinstance(evidence.get("response_sha256"),str)
            or not re.fullmatch(r"[0-9a-f]{64}",evidence["response_sha256"])
            or not isinstance(evidence.get("rows"),list)
            or not MIN_OFFICIAL_RECORDS<=len(evidence["rows"])<=MAX_OFFICIAL_RECORDS):
        raise ValueError("Unverified official current-company basics evidence")
    if (not isinstance(eligible_ids,set) or len(eligible_ids)!=1092
            or not isinstance(no_2022_ids,set) or len(no_2022_ids)!=129
            or not no_2022_ids<=eligible_ids or "1589" in eligible_ids
            or not isinstance(first_2023plus,dict)
            or set(first_2023plus)!=eligible_ids
            or type(current_day) is not date
            or type(prior_window_end) is not date
            or current_day<prior_window_end
            or (current_day-prior_window_end).days>14):
        raise ValueError("Old 129 issuer research scope or five-year proof is stale")

    by_id={}
    observed=None
    for row in evidence["rows"]:
        if not isinstance(row,dict):
            raise ValueError("Malformed TWSE company basic listing record")
        stock=row.get("公司代號")
        if not isinstance(stock,str) or not re.fullmatch(r"\d{4}",stock):
            continue
        if stock in by_id:
            raise ValueError("Duplicate official current-company source stock code")
        day=_roc_snapshot_day(row.get("出表日期"))
        if observed is None:
            observed=day
        elif day!=observed:
            raise ValueError("Mixed-vintage issuer records in single listing response")
        by_id[stock]=_listing_day(row.get("上市日期"))

    if (observed is None or not 0<=(current_day-observed).days<=14
            or observed > prior_window_end):
        raise ValueError("Official current basic-company metadata stale or future")
    if len(by_id)<MIN_OFFICIAL_RECORDS:
        raise ValueError("Official source has insufficient valid current issuers")

    counts={
        "current_twse_listing_date_on_or_before_2022":0,
        "current_twse_listing_date_2023":0,
        "current_twse_listing_date_2024":0,
        "current_twse_listing_date_2025":0,
        "current_twse_listing_date_2026":0,
        "current_twse_listing_date_missing_or_invalid":0,
        "current_2023plus_listing_but_neon_first_stored_before_current_listing_date":0,
        "current_2023plus_listing_and_first_stored_not_before_listing_date":0,
    }
    after2022=early=missing=0
    for sid in sorted(no_2022_ids):
        listing=by_id.get(sid)
        stored=first_2023plus[sid]
        if stored is not None and (
                type(stored) is not date or
                not date(2023,1,1)<=stored<prior_window_end or
                stored.weekday()>=5):
            raise ValueError("First stored after-2022 stock date invalid")
        if listing is None:
            counts["current_twse_listing_date_missing_or_invalid"]+=1
            missing+=1
        elif listing>=prior_window_end:
            raise ValueError("Current TWSE listed issuer date after prior research asof")
        elif listing<=date(2022,12,31):
            counts["current_twse_listing_date_on_or_before_2022"]+=1
            early+=1
        else:
            if listing.year not in (2023,2024,2025,2026):
                raise ValueError("Unsupported current listing observation year")
            counts[f"current_twse_listing_date_{listing.year}"]+=1
            after2022+=1
            if stored is not None and stored<listing:
                counts["current_2023plus_listing_but_neon_first_stored_before_current_listing_date"]+=1
            else:
                counts["current_2023plus_listing_and_first_stored_not_before_listing_date"]+=1
    if (after2022+early+missing!=129 or
            (counts["current_2023plus_listing_but_neon_first_stored_before_current_listing_date"]
             +counts["current_2023plus_listing_and_first_stored_not_before_listing_date"]
             !=after2022)):
        raise RuntimeError("Official listing classification groups do not conserve 129")
    return {
        "source_url":URL,
        "official_current_company_basics_response_sha256":evidence[
            "response_sha256"],
        "source_metadata_observed_at":observed.isoformat(),
        "official_current_company_rows":len(by_id),
        "currently_eligible_issuer_count":len(eligible_ids),
        "owner_2022_no_valid_source_stock_count":len(no_2022_ids),
        "current_twse_listing_after_2022_count":after2022,
        "current_twse_listing_on_or_before_2022_count":early,
        "current_twse_listing_missing_or_invalid_count":missing,
        "source_listing_date_bucket_counts":counts,
        "current_basic_company_listing_date_is_not_historic_pit_roster":True,
        "first_stored_neon_stock_bar_is_not_official_ipo_date":True,
        "transfer_relisting_or_earlier_listed_instrument_history_not_certified":True,
        "any_early_or_missing_listing_date_requires_further_official_research":
            early+missing>0,
        "original_historic_listing_or_halt_actions_fully_verified":False,
        "absence_never_authorizes_price_imputation":True,
        "model_release":"BLOCKED",
        "production_neon_writes":0,
        "line_messages_sent":0,
        "paid_services_used":False,
    }
