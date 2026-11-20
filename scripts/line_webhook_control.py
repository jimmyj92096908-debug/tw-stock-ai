"""Inspect or safely restore the original LINE Official Account webhook.

This module never changes the webhook by default. Explicit restore is pinned
to the previously verified exact original URL, gated by both --apply and an
environment flag. It does not handle any LINE user messages.
"""
from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

API = "https://api.line.me/v2/bot/channel/webhook/endpoint"
LEGACY_URL = (
    "https://br-purple-smoke-a1t9dmzz-linewebhook."
    "compute.c-1.ap-southeast-1.aws.neon.tech/"
)


def _call(method: str, token: str, payload=None, *, opener=urlopen):
    if not token or not isinstance(token, str):
        raise RuntimeError("LINE access token is not configured")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        API, data=body, method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        }
    )
    with opener(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("LINE webhook management request failed")
        data = json.load(response)
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected LINE API response")
        return data


def inspect_endpoint(token: str, *, opener=urlopen):
    data = _call("GET", token, opener=opener)
    endpoint = str(data.get("endpoint") or "")
    parts = urlsplit(endpoint)
    original = (parts.scheme == "https" and
                parts.hostname == urlsplit(LEGACY_URL).hostname and
                parts.path in ("", "/", "/webhook") and
                not parts.username and not parts.password and
                not parts.port and not parts.query and not parts.fragment)
    return {
        "active": data.get("active") is True,
        "is_original_legacy_webhook": original,
        "endpoint_path": parts.path if original else "[not-original]",
        "is_https": parts.scheme == "https",
    }


def restore_original(token: str, *, apply: bool, gate: str, opener=urlopen):
    if not apply or gate != "yes":
        raise RuntimeError("Explicit --apply and restore gate are required")
    before = inspect_endpoint(token, opener=opener)
    if before["is_original_legacy_webhook"] and before["active"]:
        return {"status": "already-original", "active": True}

    _call("PUT", token, {"endpoint": LEGACY_URL}, opener=opener)
    after = inspect_endpoint(token, opener=opener)
    if not after["is_original_legacy_webhook"] or not after["active"]:
        raise RuntimeError(
            "Original LINE webhook URL was not verified active after restore"
        )
    return {"status": "restored-original", "active": True}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only LINE webhook inspection, or explicitly gated rollback"
    )
    parser.add_argument("--action", choices=("inspect", "restore"), default="inspect")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if args.action == "inspect":
        result = inspect_endpoint(token)
    else:
        result = restore_original(
            token, apply=args.apply,
            gate=os.environ.get("LINE_WEBHOOK_RESTORE_ENABLED", "")
        )
    # Never print the LINE channel token, raw response, URL query or user data.
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
