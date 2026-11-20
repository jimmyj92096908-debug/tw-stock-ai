"""Observe LINE production routing and candidate health without any mutation.

Only two possible network calls:
1. Official LINE API GET /v2/bot/channel/webhook/endpoint.
2. Public GET /health of the isolated candidate (no credentials transmitted).

Never use PUT or POST, never send messages, never copy LINE secrets, never
interpret preflight probes as end-to-end proof or production cutover approval.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from line_webhook_control import inspect_endpoint
from line_gateway_canary import GATEWAY_URL

GATEWAY_HEALTH_URL = GATEWAY_URL.rstrip("/") + "/health"


def probe_candidate_health(*, opener=urlopen):
    request = Request(GATEWAY_HEALTH_URL, method="GET")
    try:
        with opener(request, timeout=12) as response:
            # A healthy response from an unexpected redirected address is not
            # accepted. There are no tokens or private data in this request.
            effective = response.geturl()
            return response.status == 200 and effective == GATEWAY_HEALTH_URL
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def collect_preflight(token, *, inspector=inspect_endpoint,
                      health_probe=probe_candidate_health):
    official = None
    problem = None
    if token:
        try:
            official = inspector(token)
        except Exception:
            # Never log network exception text: it may include sensitive URL.
            problem = "official_webhook_read_failed"
    else:
        problem = "official_read_token_missing"
    health = bool(health_probe())
    original_active = bool(
        official and official.get("is_original_legacy_webhook") is True
        and official.get("active") is True
    )
    observations_pass = original_active and health and not problem
    if not problem and not original_active:
        problem = "registered_webhook_not_verified_original"
    if not problem and not health:
        problem = "candidate_health_check_failed"
    return {
        "schema_version": 1,
        "assessment": "read_only_preflight_pass" if observations_pass else "blocked_or_inconclusive",
        "official_webhook_get_performed": bool(token),
        "legacy_webhook_active_and_original": original_active,
        "candidate_get_health_200": health,
        "official_signed_empty_canary_performed": False,
        "official_signed_empty_canary_passed": False,
        "real_line_message_e2e_verified": False,
        "new_gateway_channel_secrets_present_verified": False,
        "new_gateway_enabled": False,
        "production_webhook_changed": False,
        "line_message_sent": False,
        "ready_for_cutover": False,
        "blocker": problem or "official_signed_canary_and_real_e2e_still_missing",
    }


def main():
    parser = argparse.ArgumentParser(description="Non-mutating LINE endpoint readiness")
    parser.add_argument("--output", type=Path, default=Path("line-readiness-observe.json"))
    args = parser.parse_args()
    report = collect_preflight(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "assessment": report["assessment"],
        "legacy_webhook_active_and_original": report["legacy_webhook_active_and_original"],
        "candidate_get_health_200": report["candidate_get_health_200"],
        "ready_for_cutover": False,
        "blocker": report["blocker"],
    }, ensure_ascii=False))
    if report["assessment"] != "read_only_preflight_pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
