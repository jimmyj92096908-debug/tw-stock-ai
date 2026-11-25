"""Offline exact owner-reported TWSE+TPEx quarterly raw factor merge.

Standard library only. No database, network, model training or trade actions.
The producer hashes pin the feature arrays; batch receipts are checked for
count/shape only because the producer does not export the full roster IDs.
"""
from collections import Counter
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import re

VERSION="tw-raw-price-asof-bridge-1"
FEATURES=["raw_ret5","raw_ret20","raw_ma20_gap","raw_ma55_gap","raw_rsi14_fraction",
    "raw_atr14_fraction","raw_volume_vs_ma20","raw_smc_trend","raw_smc_bos_bullish",
    "raw_smc_bos_bearish","raw_smc_choch_bullish","raw_smc_choch_bearish"]
DATES="2022-12-30 2023-03-31 2023-06-30 2023-09-28 2023-12-29 2024-03-29 2024-06-28 2024-09-30 2024-12-31 2025-03-31 2025-06-30 2025-09-30 2025-12-31 2026-03-31 2026-06-30 2026-09-30 2026-11-20".split()
SPECS={
    "twse":(1092,28,15148,"9ddd6c982bcf3283a9191a7b373a72b0311d42962195269b4152312fe962074e",
        [828,838,848,848,866,877,880,895,911,915,911,896,902,912,927,940,954]),
    "tpex":(898,23,9725,"4d9b5735a16ddcb08b23d8ff8f09490f4f462f9ce0b34e98398be9a7c07405fe",
        [510,520,539,543,562,578,585,598,597,597,586,575,570,579,593,601,592]),
}
MAX_BYTES=32_000_000
ROW_KEYS={"stock_id","market","signal_date","feature_vector","prefix_source_rows","prefix_source_sha256"}
HASH=re.compile(r"[0-9a-f]{64}",re.ASCII)
CODE=re.compile(r"[0-9]{4}",re.ASCII)


def fingerprint(rows):
    return sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def strict_object(pairs):
    result={}
    for k,v in pairs:
        if k in result:
            raise ValueError("Duplicate JSON member")
        result[k]=v
    return result


def reject_constant(value):
    raise ValueError("Nonfinite JSON constant")


def private_path(raw,*,existing):
    p=Path(raw).expanduser()
    if p.is_symlink() or any(parent.is_symlink() for parent in p.parents):
        raise ValueError("No symlinked private path")
    p=p.resolve()
    if any((parent/".git").exists() for parent in p.parents):
        raise ValueError("Private panel must remain outside Git")
    if existing:
        if not p.is_file() or not 0<p.stat().st_size<=MAX_BYTES:
            raise ValueError("Bounded existing private file required")
    elif p.exists() or not p.parent.is_dir():
        raise ValueError("No overwrite; existing private directory required")
    return p


def read_panel(path):
    with path.open("rb") as f:
        raw=f.read(MAX_BYTES+1)
    if not 0<len(raw)<=MAX_BYTES:
        raise ValueError("File bound exceeded")
    return json.loads(raw,object_pairs_hook=strict_object,parse_constant=reject_constant),sha256(raw).hexdigest()


def check_rows(rows,market):
    if type(rows) is not list or not 0<len(rows)<=18564:
        raise ValueError("Bounded feature rows required")
    keys=[];counts=Counter()
    for r in rows:
        if type(r) is not dict or set(r)!=ROW_KEYS:
            raise ValueError("Unexpected feature row schema")
        sid,d,v=r["stock_id"],r["signal_date"],r["feature_vector"]
        if (r["market"]!=market or type(sid) is not str or not CODE.fullmatch(sid) or sid=="1589"
            or d not in DATES or type(v) is not list or len(v)!=len(FEATURES)
            or any(type(x) not in (int,float) or not math.isfinite(x) for x in v)
            or type(r["prefix_source_rows"]) is not int or not 240<=r["prefix_source_rows"]<=1600
            or type(r["prefix_source_sha256"]) is not str or not HASH.fullmatch(r["prefix_source_sha256"])):
            raise ValueError("Invalid private feature row")
        keys.append((d,sid));counts[d]+=1
    if keys!=sorted(set(keys)):
        raise ValueError("Duplicate or unordered stock/date keys")
    return counts,{s for d,s in keys}


def verify_panel(payload,market,spec):
    n,batches,accepted,digest,per_date=spec
    if type(payload) is not dict or set(payload)!={"summary","private_batch_receipts","private_feature_rows"}:
        raise ValueError("Unexpected owner panel structure")
    s=payload["summary"];rows=payload["private_feature_rows"];b=payload["private_batch_receipts"]
    if type(s) is not dict or type(b) is not list or len(b)!=batches:
        raise ValueError("Invalid summary or batch shape")
    exact={"schema_version":1,"scope":"OWNER_"+market.upper()+"_ALL_CURRENT_LISTED_QUARTERLY_RAW_FEATURE_PANEL",
        "eligible_stocks":n,"batch_count":batches,"requested_signal_dates":len(DATES),
        "candidate_stock_signal_pairs":n*len(DATES),"accepted_feature_rows":accepted,
        "accepted_feature_values":accepted*len(FEATURES),"feature_version":VERSION,
        "feature_names":FEATURES,"private_feature_rows_sha256":digest,
        "prefix_only_feature_computation":True,"current_roster_not_historical_pit":True,
        "official_market_calendar_independently_proven":False,"daily_full_five_year_factor_panel_recomputed":False,
        "forward_labels_created":False,"corporate_actions_adjusted":False,"historical_pit_total_return_verified":False,
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}
    for k,v in exact.items():
        if type(s.get(k)) is not type(v) or s[k]!=v:
            raise ValueError("Owner summary contract changed")
    counts,ids=check_rows(rows,market)
    if len(rows)!=accepted or len(ids)>n or fingerprint(rows)!=digest:
        raise ValueError("Owner feature payload hash/count changed")
    dates=[{"signal_date":d,"accepted":a,"excluded":({"incomplete_240_observed_market_dates":n-a} if a<n else {})}
           for d,a in zip(DATES,per_date)]
    if s.get("signal_date_outcomes")!=dates or [counts[d] for d in DATES]!=per_date:
        raise ValueError("Signal date reconciliation failed")
    for i,r in enumerate(b):
        expected_size=min(40,n-i*40)
        if (type(r) is not dict or set(r)!={"issuer_count","accepted_rows","feature_rows_sha256"}
            or type(r["issuer_count"]) is not int or r["issuer_count"]!=expected_size
            or type(r["accepted_rows"]) is not int or not 0<=r["accepted_rows"]<=expected_size*len(DATES)
            or type(r["feature_rows_sha256"]) is not str or not HASH.fullmatch(r["feature_rows_sha256"])):
            raise ValueError("Invalid batch receipt")
    if sum(r["accepted_rows"] for r in b)!=accepted:
        raise ValueError("Batch count conservation failed")
    return rows,ids,counts


def merge(twse,tpex,*,specs=None):
    specs=SPECS if specs is None else specs
    a,ids_a,ca=verify_panel(twse,"twse",specs["twse"])
    b,ids_b,cb=verify_panel(tpex,"tpex",specs["tpex"])
    if ids_a&ids_b:
        raise ValueError("Current market issuer IDs intersect")
    rows=sorted(a+b,key=lambda r:(r["signal_date"],r["market"],r["stock_id"]))
    n=sum(v[0] for v in specs.values())
    if len(rows)!=sum(v[2] for v in specs.values()):
        raise ValueError("Merged row conservation failed")
    return {"schema_version":1,"scope":"OWNER_TWSE_TPEX_MERGED_QUARTERLY_RAW_FEATURE_PANEL",
        "candidate_current_market_stocks":n,"distinct_issuers_with_any_accepted_feature":len(ids_a|ids_b),
        "requested_signal_dates":len(DATES),"candidate_stock_signal_pairs":n*len(DATES),
        "accepted_feature_rows":len(rows),"accepted_feature_values":len(rows)*len(FEATURES),
        "market_accepted_rows":{"twse":len(a),"tpex":len(b)},
        "signal_date_outcomes":[{"signal_date":d,"twse_accepted":ca[d],"tpex_accepted":cb[d],
            "accepted":ca[d]+cb[d],"excluded":n-ca[d]-cb[d]} for d in DATES],
        "feature_names":FEATURES,"feature_version":VERSION,"private_feature_rows_sha256":fingerprint(rows),
        "owner_reported_feature_hashes_replayed_exact":True,"batch_receipt_counts_checked":True,
        "batch_receipt_hashes_independently_recomputed":False,"full_roster_identity_independently_proven":False,
        "current_roster_not_historical_pit":True,"official_market_calendar_independently_proven":False,
        "daily_full_five_year_factor_panel_recomputed":False,"corporate_actions_adjusted":False,
        "forward_labels_created":False,"historical_pit_total_return_verified":False,
        "chip_factors_integrated":False,"production_neon_reads":0,"production_neon_writes":0,
        "line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"},rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("twse","tpex","out"):
        p.add_argument("--"+name,required=True)
    a=p.parse_args()
    stage="PRIVATE_INPUT"
    try:
        paths=[private_path(a.twse,existing=True),private_path(a.tpex,existing=True),private_path(a.out,existing=False)]
        if len(set(paths))!=3:
            raise ValueError("Distinct paths required")
        twse,ha=read_panel(paths[0]);tpex,hb=read_panel(paths[1])
        stage="VERIFY_AND_MERGE"
        summary,rows=merge(twse,tpex)
        summary["input_file_sha256"]=[ha,hb]
        stage="PRIVATE_OUTPUT"
        with paths[2].open("x",encoding="utf-8") as f:
            json.dump({"summary":summary,"private_feature_rows":rows},f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(summary,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; zero Neon/LINE actions") from None


if __name__=="__main__":
    main()
