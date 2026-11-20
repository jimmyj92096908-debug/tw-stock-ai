"""LINE's signed, empty-event webhook endpoint test for the isolated gateway.

No LINE user IDs, reply tokens, messages, or webhook URL mutations. The LINE
platform sends its own signed empty test event to the pinned staging URL.
Requires an explicit manual execution gate.
"""
from __future__ import annotations

import argparse
import json
import os
from urllib.request import Request, urlopen

LINE_TEST_API = "https://api.line.me/v2/bot/channel/webhook/test"
GATEWAY_URL = (
    "https://br-purple-smoke-a1t9dmzz-linestockgateway."
    "compute.c-1.ap-southeast-1.aws.neon.tech/"
)


def run_canary(token: str, *, apply: bool, gate: str, opener=urlopen) -> dict:
    if not apply or gate != "yes":
        raise RuntimeError("An explicit manual canary test gate is required")
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is required")
    payload = json.dumps({"endpoint": GATEWAY_URL}).encode("utf-8")
    request = Request(
        LINE_TEST_API, data=payload, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    with opener(request, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError("LINE canary API transport did not return HTTP 200")
        result = json.load(response)

    if not isinstance(result, dict):
        raise RuntimeError("Malformed LINE canary response")
    success = result.get("success") is True
    status = result.get("statusCode")
    if not success or status != 200:
        # No LINE response details, user data, credentials, or endpoint URL in
        # the error; caller sees only an aggregate status code.
        raise RuntimeError(f"Gateway signed canary failed (status={status})")
    return {
        "gateway": "linestockgateway",
        "signed_empty_event_accepted": True,
        "status_code": 200,
        "registered_endpoint_unchanged": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Test disabled-by-default Neon gateway with LINE official signed empty event")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = run_canary(
        os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
        apply=args.apply,
        gate=os.environ.get("LINE_CANARY_TEST_ENABLED", ""),
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
