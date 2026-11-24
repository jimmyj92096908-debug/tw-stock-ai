"""Read-only owner-local audit of all frozen five-stock monthly cache pairs."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from scripts import owner_twse_direct_monthly_five_stock as five
from scripts import owner_twse_direct_monthly_source_canary as c
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m
from scripts import owner_quarterly_chip_vintage_coverage_readonly as chip

def audit(stocks,directory):
    directory=c.private_dir(directory)
    counts=Counter();years=Counter();details=[];rows=0
    for year in range(2023,2027):
        for quarter in range(1,5):
            q=five.queue_for(stocks,year,quarter)
            for stock,month in q:
                stem=f"twse-stock-day-{stock}-{month}"
                raw=directory/(stem+".response.json");meta=directory/(stem+".receipt.json")
                status="MISSING"
                try:
                    if raw.is_symlink() or meta.is_symlink():
                        raise ValueError("symlink")
                    if raw.exists()!=meta.exists():
                        status="INCOMPLETE_PAIR"
                    elif raw.exists():
                        status="INVALID_PAIR"
                        if not raw.is_file() or not meta.is_file() or raw.stat().st_size>c.LIMIT or meta.stat().st_size>4096:
                            raise ValueError("bounds")
                        blob=raw.read_bytes()
                        proof=json.loads(meta.read_text(encoding="utf-8"),object_pairs_hook=m.strict_object)
                        bars=c.parse_month(blob,stock,month,queue=q)
                        if (proof.get("scope")!="OWNER_TWSE_STOCK_DAY_DIRECT_CAPTURE"
                            or proof.get("stock_id")!=stock or proof.get("month")!=month
                            or proof.get("response_sha256")!=sha256(blob).hexdigest()
                            or proof.get("row_count")!=len(bars) or proof.get("endpoint")!=c.ENDPOINT):
                            raise ValueError("receipt mismatch")
                        rows+=len(bars);years[str(year)]+=1;status="VALID"
                except Exception:
                    status="INVALID_PAIR"
                counts[status]+=1
                if status!="VALID":
                    details.append({"stock_id":stock,"month":month,"status":status})
    return {"scope":"OWNER_FIVE_STOCK_CACHE_OFFLINE_AUDIT","expected_months":235,
        "valid_months":counts["VALID"],"valid_source_rows":rows,"year_valid_months":dict(years),
        "status_counts":dict(counts),"first_unverified":details[0] if details else None,
        "invalid_or_incomplete_pairs":[d for d in details if d["status"]!="MISSING"],
        "safe_to_resume_missing_only":not(counts["INVALID_PAIR"] or counts["INCOMPLETE_PAIR"]),
        "frozen_sample_sha256":m.fingerprint(list(stocks)),"historical_publication_vintage_verified":False,
        "official_calendar_completeness_verified":False,"production_neon_reads":0,
        "production_neon_writes":0,"official_requests":0,"line_messages_sent":0,"model_release":"BLOCKED"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel",required=True);p.add_argument("--cache-dir",required=True)
    a=p.parse_args()
    try:
        payload,_=m.read_panel(m.private_path(a.panel,existing=True))
        print(json.dumps(audit(five.select(chip.verify_input(payload)),a.cache_dir),allow_nan=False))
    except Exception:
        raise SystemExit("Offline audit failed safely; no writes or requests") from None
if __name__=="__main__":
    main()
