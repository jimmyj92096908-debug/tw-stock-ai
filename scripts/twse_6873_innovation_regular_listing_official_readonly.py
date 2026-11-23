"""Owner-only reconciliation of TWSE 6873 innovation -> regular board event dates.

Public official TWSE new-listings page proves 2023-03-06 innovation-board
first trading. Previous owner PR234/235 authenticated current company listing
date 2024-09-26 and Neon first valid stored source date 2023-03-06.
No Neon connection, AES decrypt, stored price, write or model actions.
The issuer is not an OTC-to-TWSE market transfer.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2022_official_current_listing_date_triage import (
    validate_private_one_conflict_against_prior_receipt,
)
from scripts.twse_2022_aes_neon_eligible_density_readonly import (
    SCOPE as PRIOR_SCOPE,
)

SCOPE="OWNER_TWSE_6873_HISTORIC_INNOVATION_REGULAR_DATE_RECONCILIATION"
URL="https://www.twse.com.tw/company/newlisting?response=html&yy="
STOCK="6873"
STOCK_NAME="泓德能源-創"
EXPECTED_INITIAL=date(2023,3,6)
EXPECTED_REGULAR=date(2024,9,26)
MAX_BYTES=6_000_000
MAX_REPORT_BYTES=13000


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[]
        self.row=None
        self.cell=None

    def handle_starttag(self,tag,attrs):
        if tag=="tr":
            if self.row is not None:
                raise ValueError("TWSE listing table contains nested rows")
            self.row=[]
        elif tag in ("td","th") and self.row is not None:
            if self.cell is not None:
                raise ValueError("TWSE listing table contains nested data cell")
            self.cell=[]

    def handle_data(self,data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell=None
        elif tag=="tr" and self.row is not None:
            if self.cell is not None:
                raise ValueError("Unclosed TWSE listed-company record cell")
            if self.row:
                self.rows.append(tuple(self.row))
            self.row=None


def _roc_dot(text):
    if not isinstance(text,str) or not re.fullmatch(r"\d{3}[./]\d{2}[./]\d{2}",text):
        raise ValueError("Expected official TWSE ROC dotted listing date")
    return date(1911+int(text[:3]),int(text[4:6]),int(text[7:9]))


def fetch_twse_historic_listings(*,get=None):
    if get is None:
        import requests
        get=requests.get
    r=get(URL,timeout=(8,35),allow_redirects=False,headers={
        "Accept":"text/html",
        "User-Agent":"tw-stock-ai-owner-6873-official-historic-innovation-listing-check",
    })
    r.raise_for_status()
    endpoint=urlparse(r.url)
    if (r.status_code!=200 or endpoint.scheme!="https"
            or endpoint.hostname!="www.twse.com.tw"
            or endpoint.path!="/company/newlisting"
            or endpoint.query!="response=html&yy="):
        raise ValueError("Historic listing response changed TWSE HTTPS official endpoint")
    data=r.content
    if not isinstance(data,bytes) or not 0<len(data)<=MAX_BYTES:
        raise ValueError("Historic TWSE listing official page invalid size")
    parser=_TableRows()
    parser.feed(data.decode("utf-8"))
    parser.close()
    if not 50<=len(parser.rows)<=2000:
        raise ValueError("Historic official TWSE listing rows incomplete")
    return {
        "endpoint":URL,
        "source_sha256":sha256(data).hexdigest(),
        "rows":parser.rows,
    }


def reconcile(prior_234,prior_235,historic):
    if not isinstance(prior_234,dict) or not isinstance(prior_235,dict):
        raise ValueError("Both original owner PR234 and PR235 private reports required")
    # Full equality of original official response SHA, 129 cohort and
    # one source/listing mismatch before using any issuer-specific evidence.
    official=prior_235.get(
        "owner_129_no2022_current_twse_official_listing_date_triage")
    validate_private_one_conflict_against_prior_receipt(
        prior_234,official,expected_scope=PRIOR_SCOPE)
    if (prior_235.get("schema_version")!=1
            or prior_235.get("scope")!=PRIOR_SCOPE
            or prior_235.get("model_release")!="BLOCKED"
            or prior_235.get("production_neon_writes")!=0
            or prior_235.get("line_messages_sent")!=0
            or prior_235.get("official_current_listed_eligible_twse_issuers")!=1092
            or prior_235.get("aes_neon_current_listed_stocks_with_all_246_source_dates")!=825
            or prior_235.get("year")!=2022):
        raise ValueError("Original owner one-stock private receipt changed")
    conflict=official["owner_private_official_listing_first_neon_date_conflicts"]
    if len(conflict)!=1:
        raise ValueError("Expected exactly one authenticated owner-date mismatch")
    item=conflict[0]
    if (not isinstance(item,dict)
            or item.get("stock_id")!=STOCK
            or item.get("first_valid_neon_source_date")!=EXPECTED_INITIAL.isoformat()
            or item.get("current_official_twse_listing_date")!=EXPECTED_REGULAR.isoformat()
            or item.get("stored_source_precedes_current_listing_by_calendar_days")!=570
            or item.get("reason_unresolved_not_authorized_to_modify_price") is not True):
        raise ValueError("Owner 6873 historic listing discrepancy not the expected source")
    if (not isinstance(historic,dict) or historic.get("endpoint")!=URL
            or not re.fullmatch(r"[0-9a-f]{64}",str(historic.get("source_sha256","")))
            or not isinstance(historic.get("rows"),list)):
        raise ValueError("Missing official TWSE historic listing evidence")
    matching=[]
    for row in historic["rows"]:
        if not isinstance(row,(list,tuple)):
            raise ValueError("Invalid official table row")
        stock_indexes=[i for i,v in enumerate(row) if v==STOCK]
        if stock_indexes:
            if len(stock_indexes)!=1 or stock_indexes[0]!=0 or len(row)<13:
                raise ValueError("Official listing issuer row format drifted")
            matching.append(row)
    if len(matching)!=1:
        raise ValueError("Official historic 6873 listing row missing or duplicated")
    # TWSE current HTML newlisting columns:
    # stock_code, company, application_date, chairman, capital,
    # committee, board, contract, regulator, *first_traded_date*,
    # underwriter, offering_price, remarks.
    matched=matching[0]
    if (matched[1]!=STOCK_NAME or
            matched[12]!="創新板" or
            _roc_dot(matched[9])!=EXPECTED_INITIAL):
        raise ValueError("Cannot independently corroborate official 6873 innovation listing day")
    return {
        "schema_version":1,
        "scope":SCOPE,
        "stock_id":STOCK,
        "research_prior_owner_single_conflict_stock_count":1,
        "prior_owner_neon_first_valid_source_date":EXPECTED_INITIAL.isoformat(),
        "official_2023_initial_twse_innovation_board_trading_date":EXPECTED_INITIAL.isoformat(),
        "official_latest_current_regular_board_listing_date":EXPECTED_REGULAR.isoformat(),
        "time_between_innovation_listing_and_regular_board_days":570,
        "recorded_current_official_listing_date_is_regular_board_switch_not_first_twse_listing":True,
        "historic_first_twse_board":"TWSE_INNOVATION_BOARD",
        "regular_board_switch_event":"TWSE_INNOVATION_TO_REGULAR_BOARD",
        "not_tpex_to_twse_transfer":True,
        "public_official_twse_newlisting_url":URL,
        "public_official_twse_newlisting_response_sha256":historic["source_sha256"],
        "prior_current_official_basic_source_sha256":official[
            "official_current_company_basics_response_sha256"],
        "prior_report_source_date_mismatch_reclassified_as_board_transition":True,
        "individual_neon_price_ohlcv_economics_verified":False,
        "complete_first_listing_price_and_all_corporate_actions_verified":False,
        "historical_pit_issuer_universe_verified":False,
        "historical_halt_or_2022_116_internal_gaps_resolved":False,
        "model_release":"BLOCKED",
        "neon_reads":0,
        "production_neon_writes":0,
        "line_messages_sent":0,
        "extra_paid_service_used":False,
    }


def main():
    p=argparse.ArgumentParser(
        description="Owner-only verification that 6873 first TWSE innovation trading was 2023-03-06, 2024-09-26 regular board")
    p.add_argument("--prior-234-official-report",required=True)
    p.add_argument("--prior-235-conflict-report",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    try:
        a=_private_file(args.prior_234_official_report,should_exist=True)
        b=_private_file(args.prior_235_conflict_report,should_exist=True)
        target=_private_file(args.out,should_exist=False)
        if len({a,b,target})!=3:
            raise ValueError("Private official inputs/output must differ")
        # Validate private old report *before* using any public HTTP call.
        original=json.loads(a.read_text(encoding="utf-8"))
        newer=json.loads(b.read_text(encoding="utf-8"))
        # A one-stock old/new comparison must still pass under the fresh
        # historic page; reconcile() fails closed if original proof drifts.
        report=reconcile(original,newer,fetch_twse_historic_listings())
        payload=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
        if len(payload.encode("utf-8"))>MAX_REPORT_BYTES:
            raise ValueError("Owner event provenance report oversized")
        with target.open("x",encoding="utf-8") as fp:
            fp.write(payload)
        print(json.dumps({
            "status":"TWSE_6873_INNOVATION_TO_REGULAR_LISTING_EVENT_PROVENANCE_PASS",
            "stock_id":STOCK,
            "first_twse_innovation_day":EXPECTED_INITIAL.isoformat(),
            "converted_to_regular_board_on":EXPECTED_REGULAR.isoformat(),
            "source_date_conflict_reclassified_as_board_transition":True,
            "per_stock_ohlcv_and_total_return_approved":False,
            "neon_writes":0,
            "line_messages_sent":0,
            "model_release":"BLOCKED",
        },ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "TWSE 6873 2023 innovation/2024 regular official event verification FAILED; "
            "no Neon reads/writes, LINE, confidential values or prices printed"
        ) from None


if __name__=="__main__":
    main()
