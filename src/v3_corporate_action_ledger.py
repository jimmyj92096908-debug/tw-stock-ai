"""Offline V3 corporate-action entitlement accounting kernel.

Supports gross cash dividends and explicitly immediate, exact whole-share
conversions only. No inferred ratios, deferred stock dividends, tax, rights
subscriptions or fractional cash-in-lieu. No production data access.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re

from src.v3_probability_calibration import _day


def _amount(value):
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError("Exact decimal amount required")
    try:
        x = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid amount") from exc
    if not x.is_finite() or x < 0 or x > Decimal("100000000000000"):
        raise ValueError("Invalid amount")
    return x


def opening_action_step(*, session_date, previous_session_date, holdings,
                        pending_dividends, applied_event_ids, actions):
    """Apply events before today's trades using prior-close share entitlement.

    Caller must prove actual exchange-calendar continuity, action completeness,
    public availability and authentic source evidence. The source hash format
    check is NOT authentication. At most one action per stock per session;
    simultaneous/mixed events are rejected rather than guessed.
    Dividends enter receivables on ex-date and available cash on an explicitly
    supplied credit session (not necessarily the official payment date).
    All shares, including odd lots, are retained. Unsupported fractional
    conversion fails closed. Outputs are new state; inputs are not mutated.
    """
    day, prev = _day(session_date), _day(previous_session_date)
    if day <= prev:
        raise ValueError("Nonchronological session")
    if not isinstance(holdings,dict):
        raise ValueError("Holdings map required")
    positions = dict(holdings)
    for s,q in positions.items():
        if not isinstance(s,str) or not s.isascii() or not s.isdigit() or s=="1589" or type(q) is not int or not 0 <= q <= 10**10:
            raise ValueError("Invalid holding")
    if not isinstance(applied_event_ids,(list,tuple)) or any(not isinstance(x,str) or not x for x in applied_event_ids):
        raise ValueError("Invalid applied event IDs")
    seen = set(applied_event_ids)
    if len(seen) != len(applied_event_ids):
        raise ValueError("Duplicate applied event ID")
    if not isinstance(pending_dividends,list) or not isinstance(actions,list):
        raise ValueError("Expected event and receivable lists")
    pending, credited, pending_ids = [], Decimal(0), set()
    for item in pending_dividends:
        ident = item["event_id"]
        due = _day(item["credit_session"])
        value = _amount(item["amount"])
        if ident not in seen or ident in pending_ids or due <= prev or value <= 0:
            raise ValueError("Invalid prior receivable state")
        pending_ids.add(ident)
        if due <= day:
            credited += value
        else:
            pending.append(dict(event_id=ident,credit_session=due.isoformat(),amount=str(value)))
    created = Decimal(0)
    touched = set()
    for a in actions:
        s, ident = a["stock_id"], a["event_id"]
        if (not isinstance(ident,str) or not ident or ident in seen
                or not isinstance(s,str) or not s.isascii() or not s.isdigit()
                or s=="1589" or s in touched):
            raise ValueError("Duplicate, mixed or excluded action")
        if (a.get("market") not in ("TWSE","TPEx")
                or a.get("currently_listed") is not True
                or a.get("terms_verified") is not True
                or not isinstance(a.get("source_sha256"),str)
                or re.fullmatch(r"[0-9a-f]{64}",a["source_sha256"]) is None):
            raise ValueError("Missing declared source evidence")
        if _day(a["effective_session"]) != day or _day(a["public_date"]) >= day:
            raise ValueError("Action must be publicly known before effective session")
        q = positions.get(s,0)
        if a["kind"] == "CASH_DIVIDEND":
            if set(a) & {"new_shares","old_shares","delivery_session"}:
                raise ValueError("Mixed event not supported")
            due = _day(a["credit_session"])
            per_share = _amount(a["cash_per_share"])
            if due <= day or per_share <= 0:
                raise ValueError("Invalid dividend terms")
            value = per_share*q
            if value:
                created += value
                pending.append(dict(event_id=ident,credit_session=due.isoformat(),amount=str(value)))
        elif a["kind"] == "IMMEDIATE_SHARE_CONVERSION":
            if set(a) & {"cash_per_share","credit_session","cash_in_lieu"}:
                raise ValueError("Mixed event not supported")
            old,new = a["old_shares"],a["new_shares"]
            if (type(old) is not int or type(new) is not int
                    or not 1<=old<=10**6 or not 1<=new<=10**6 or old==new
                    or _day(a["delivery_session"])!=day):
                raise ValueError("Invalid or deferred conversion")
            converted = Fraction(q*new,old)
            if converted.denominator != 1 or converted > 10**10:
                raise ValueError("Fractional or excessive conversion unsupported")
            if q:
                positions[s] = int(converted)
        else:
            raise ValueError("Unsupported corporate action")
        seen.add(ident)
        touched.add(s)
    return {"holdings":positions,"pending_dividends":pending,
            "applied_event_ids":sorted(seen),"gross_cash_credited":str(credited),
            "gross_receivable_created":str(created),
            "gross_receivable_balance":str(sum((_amount(x["amount"]) for x in pending),Decimal(0))),
            "source_provenance_verified":False,"calendar_completeness_verified":False,
            "taxes_supported":False,"integrated_portfolio_ledger":False,
            "model_release":"BLOCKED","trading_approved":False}
