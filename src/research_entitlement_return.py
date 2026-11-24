"""Offline economic holding-return arithmetic, NOT official evidence authentication.

Caller-supplied action coverage and terms are hypotheses until independently
authenticated. No adjusted-price multiplier is interpreted as cash proceeds.
Gross, pre-tax, mark-to-market entitlement model: cash held, not reinvested;
fractional share entitlements valued at exit close, not assumed deliverable.
Unsupported or ambiguous events reject the entire signal-date cohort.
"""
from datetime import date
from decimal import Decimal
from fractions import Fraction
import re
from hashlib import sha256
import json

VERSION="cash-held-share-entitlement-hypothesis-v1"
CODE=re.compile(r"[0-9]{4}",re.ASCII)
HASH=re.compile(r"[0-9a-f]{64}",re.ASCII)
NUMBER=re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,12})?",re.ASCII)
MAX_RETURN=Fraction(10)
EVENT_KEYS={"event_id","ex_date","kind","cash_per_pre_event_share","shares_per_pre_event_share","evidence_sha256"}
SUPPORTED={"CASH_DIVIDEND","STOCK_DIVIDEND","STOCK_SPLIT","REVERSE_SPLIT"}


def day(s):
    if type(s) is not str:
        raise ValueError("Canonical date required")
    d=date.fromisoformat(s)
    if d.isoformat()!=s:
        raise ValueError("Canonical date required")
    return d


def num(s,*,positive=False):
    if type(s) is not str or not NUMBER.fullmatch(s):
        raise ValueError("Exact bounded nonnegative decimal string required")
    v=Fraction(Decimal(s))
    if positive and v<=0:
        raise ValueError("Positive value required")
    return v


def digest(s):
    if type(s) is not str or not HASH.fullmatch(s):
        raise ValueError("Evidence fingerprint required")


def rounded(v):
    """Exact rational half-even rounding, canonical fixed 12 decimals."""
    scale=10**12
    magnitude,remainder=divmod(abs(v.numerator)*scale,v.denominator)
    if 2*remainder>v.denominator or (2*remainder==v.denominator and magnitude%2):
        magnitude+=1
    whole,fraction=divmod(magnitude,scale)
    sign="-" if v<0 and magnitude else ""
    return f"{sign}{whole}.{fraction:012d}"


def hypothetical_return(*,market,stock_id,signal_date,sessions,prices,actions,coverage):
    """Exact arithmetic on six common post-signal sessions, entry 1, exit 6.
    Coverage is an explicit supplied assertion, never independently proven here.
    Ex-date at entry close creates no entitlement. Exit-day ex-date does.
    Same-date separate events are rejected rather than assuming their ordering.
    """
    if (market not in ("twse","tpex") or type(stock_id) is not str
        or not CODE.fullmatch(stock_id) or stock_id=="1589"):
        raise ValueError("Invalid market or issuer")
    signal=day(signal_date)
    if type(sessions) is not list or len(sessions)!=6:
        raise ValueError("Exactly six supplied common sessions required")
    dates=[day(s) for s in sessions]
    if dates!=sorted(set(dates)) or not signal<dates[0] or any(d.weekday()>=5 for d in dates):
        raise ValueError("Unordered or invalid supplied sessions")
    entry,exit_=dates[0],dates[-1]
    if type(prices) is not list or len(prices)!=6:
        raise ValueError("All six path prices required")
    closes=[]
    for p,d in zip(prices,dates):
        if type(p) is not dict or set(p)!={"trade_date","close","evidence_sha256"} or day(p["trade_date"])!=d:
            raise ValueError("Misaligned raw close evidence")
        digest(p["evidence_sha256"]);closes.append(num(p["close"],positive=True))
    if (type(coverage) is not dict or set(coverage)!={"market","stock_id","start_exclusive","end_inclusive","all_action_types_covered_asserted","evidence_sha256"}
        or coverage["market"]!=market or coverage["stock_id"]!=stock_id
        or day(coverage["start_exclusive"])!=entry or day(coverage["end_inclusive"])!=exit_
        or coverage["all_action_types_covered_asserted"] is not True):
        raise ValueError("Missing explicit complete holding-period action coverage assertion")
    digest(coverage["evidence_sha256"])
    if type(actions) is not list or len(actions)>32:
        raise ValueError("Bounded complete supplied action set required")
    shares=Fraction(1);cash=Fraction(0);seen_ids=set();seen_dates=set();previous=None
    for a in actions:
        if type(a) is not dict or set(a)!=EVENT_KEYS or a["kind"] not in SUPPORTED:
            raise ValueError("Unsupported or ambiguous corporate action")
        d=day(a["ex_date"]);event_id=a["event_id"]
        if (type(event_id) is not str or not 1<=len(event_id)<=128 or event_id in seen_ids
            or d in seen_dates or d not in dates or not entry<d<=exit_
            or previous is not None and d<=previous):
            raise ValueError("Duplicate, out-of-window or ambiguous same-day event")
        digest(a["evidence_sha256"])
        amount=num(a["cash_per_pre_event_share"])
        factor=num(a["shares_per_pre_event_share"],positive=True)
        kind=a["kind"]
        if (kind=="CASH_DIVIDEND" and (amount<=0 or factor!=1)
            or kind=="STOCK_DIVIDEND" and (amount!=0 or factor<=1)
            or kind=="STOCK_SPLIT" and (amount!=0 or factor<=1)
            or kind=="REVERSE_SPLIT" and (amount!=0 or factor>=1)
            or factor>100):
            raise ValueError("Inconsistent event economics")
        cash+=shares*amount
        shares*=factor
        seen_ids.add(event_id);seen_dates.add(d);previous=d
    raw=closes[-1]/closes[0]-1
    economic=(shares*closes[-1]+cash)/closes[0]-1
    if not -1<raw<=MAX_RETURN or not -1<economic<=MAX_RETURN:
        raise ValueError("Return outside fixed research bounds")
    return {"market":market,"stock_id":stock_id,"signal_date":signal_date,
        "entry_date":sessions[0],"exit_date":sessions[-1],"raw_price_return":rounded(raw),
        "hypothetical_gross_entitlement_return":rounded(economic),
        "cash_entitlement_per_initial_share":rounded(cash),"exit_share_entitlement":rounded(shares),
        "event_count":len(actions),"method":VERSION,"supplied_evidence_not_authenticated":True,
        "historical_total_return_verified":False,"cash_payment_timing_verified":False,
        "executable_fractional_share_delivery_verified":False,"model_release":"BLOCKED"}


def whole_cohort(expected_keys,observations,*,label_cutoff):
    """Fail closed on any missing member/unsupported action, no survivor-only labels."""
    cutoff=day(label_cutoff)
    if type(expected_keys) is not list or not 5<=len(expected_keys)<=1990:
        raise ValueError("Explicit frozen cohort required")
    if any(type(k) is not tuple or len(k)!=2 for k in expected_keys) or len(set(expected_keys))!=len(expected_keys):
        raise ValueError("Duplicate or malformed cohort keys")
    if type(observations) is not list or len(observations)!=len(expected_keys):
        raise ValueError("Incomplete supplied cohort")
    results=[hypothetical_return(**row) for row in observations]
    keys=[(r["market"],r["stock_id"]) for r in results]
    if len(set(keys))!=len(keys) or set(keys)!=set(expected_keys):
        raise ValueError("Missing or foreign cohort member")
    if len({(r["signal_date"],r["entry_date"],r["exit_date"]) for r in results})!=1:
        raise ValueError("Unaligned cohort windows")
    if any(day(r["exit_date"])>cutoff for r in results):
        raise ValueError("Unmatured return")
    if len({tuple(x["sessions"]) for x in observations})!=1:
        raise ValueError("Different intermediate session paths")
    results.sort(key=lambda r:(r["market"],r["stock_id"]))
    return {"scope":"OFFLINE_HYPOTHETICAL_ECONOMIC_LABEL_COHORT",
        "schema_version":1,"method":VERSION,"candidate_rows":len(results),
        "hypothetical_rows":len(results),"approved_total_return_labels":0,
        "label_cutoff":label_cutoff,"private_rows_sha256":sha256(json.dumps(results,sort_keys=True,
            separators=(",",":"),allow_nan=False).encode()).hexdigest(),
        "official_calendar_verified":False,"official_action_coverage_verified":False,
        "source_vintage_verified":False,"model_trained":False,"production_neon_reads":0,
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,
        "model_release":"BLOCKED"},results
