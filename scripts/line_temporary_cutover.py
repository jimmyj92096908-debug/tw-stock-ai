"""Bounded LINE Official Account webhook trial with pinned automatic rollback.

Production action requires both --apply and LINE_TEMPORARY_CUTOVER_ENABLED=yes.
No user IDs, messages, credentials, or token-bearing responses are logged.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

LINE_API = 'https://api.line.me/v2/bot/channel/webhook/endpoint'
LEGACY_URL = 'https://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech/'
CANDIDATE_URL = 'https://br-purple-smoke-a1t9dmzz-linestockgateway.compute.c-1.ap-southeast-1.aws.neon.tech/'


class DenyRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _opener():
    return build_opener(DenyRedirect())


def _official(token: str, method: str, target: str | None = None, opener=None):
    if not token:
        raise RuntimeError('LINE token is missing')
    body = json.dumps({'endpoint': target}).encode('utf-8') if target else None
    req = Request(
        LINE_API, method=method, data=body,
        headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/json',
            **({'Content-Type': 'application/json'} if body else {})
        }
    )
    try:
        with (opener or _opener()).open(req, timeout=15) as reply:
            if reply.status != 200:
                raise RuntimeError('Unexpected HTTP status')
            response = json.load(reply)
            if not isinstance(response, dict):
                raise RuntimeError('Unexpected LINE response')
            return response
    except Exception:
        raise RuntimeError('LINE webhook configuration request failed') from None


def _is_fixed_url(candidate: str, expected: str) -> bool:
    try:
        found, wanted = urlsplit(candidate), urlsplit(expected)
        return (found.scheme == 'https' and found.hostname == wanted.hostname and
                found.path in ('', '/', '/webhook') and not found.username and
                not found.password and not found.port and not found.query and
                not found.fragment)
    except ValueError:
        return False


def _read(token: str, opener=None):
    data = _official(token, 'GET', opener=opener)
    return {'active': data.get('active') is True,
            'original': _is_fixed_url(str(data.get('endpoint') or ''), LEGACY_URL),
            'candidate': _is_fixed_url(str(data.get('endpoint') or ''), CANDIDATE_URL)}


def _candidate_healthy(opener=None) -> bool:
    url = CANDIDATE_URL.rstrip('/') + '/health'
    try:
        with (opener or _opener()).open(Request(url, method='GET'), timeout=12) as reply:
            return reply.status == 200 and reply.geturl() == url
    except Exception:
        return False


def _candidate_enabled(opener=None) -> bool:
    """Invalid signature: enabled gateway returns 401, disabled returns 503.

    Both paths reject the probe before reading a database or a LINE event.
    """
    req = Request(
        CANDIDATE_URL, method='POST',
        data=b'{"destination":"preflight","events":[]}',
        headers={'Content-Type':'application/json', 'x-line-signature':'invalid-preflight'}
    )
    try:
        with (opener or _opener()).open(req, timeout=12):
            return False
    except HTTPError as exc:
        return exc.code == 401
    except Exception:
        return False


def restore(token: str, *, opener=None, sleep=time.sleep) -> None:
    """Pinned rollback. Refuses to overwrite unexpected third-party destinations."""
    error = None
    for attempt in range(3):
        try:
            current = _read(token, opener=opener)
            if current['original'] and current['active']:
                print('ROLLBACK_VERIFIED original_active=true', flush=True)
                return
            if not current['candidate']:
                raise RuntimeError('Unexpected webhook destination: manual review required')
            _official(token, 'PUT', LEGACY_URL, opener=opener)
            after = _read(token, opener=opener)
            if after['original'] and after['active']:
                print('ROLLBACK_VERIFIED original_active=true', flush=True)
                return
            raise RuntimeError('Rollback did not verify the original active endpoint')
        except Exception:
            error = 'Rollback not verified; use LINE Webhook Safe Legacy Restore immediately'
            if attempt < 2:
                sleep(2)
    raise RuntimeError(error)


def trial(token: str, duration: int, *, opener=None, sleep=time.sleep) -> None:
    if not 60 <= duration <= 240:
        raise RuntimeError('Duration must be between 60 and 240 seconds')
    if not _candidate_healthy(opener):
        raise RuntimeError('Candidate health unavailable, trial aborted')
    if not _candidate_enabled(opener):
        raise RuntimeError('Candidate enable gate has not been verified, trial aborted')
    old = _read(token, opener=opener)
    if not old['active'] or not old['original']:
        raise RuntimeError('Original webhook is not active, trial aborted')
    print('PREFLIGHT_OK original_active=true candidate_health_200=true candidate_enabled_probe=true', flush=True)
    # Treat a failed PUT as potentially applied: always attempt safe restore.
    try:
        _official(token, 'PUT', CANDIDATE_URL, opener=opener)
        now = _read(token, opener=opener)
        if not now['candidate'] or not now['active']:
            raise RuntimeError('Candidate not confirmed after switch')
        print(f'TRIAL_ACTIVE configured_candidate=true duration_seconds={duration}', flush=True)
        print('ACTION_NOW: send 2330, 聯茂, 清單, 資料狀態, then one ordinary message in LINE.', flush=True)
        sleep(duration)
    finally:
        restore(token, opener=opener, sleep=sleep)


def _cancel(signum, frame):
    raise KeyboardInterrupt('Trial interrupted: running safe rollback')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=('trial', 'restore'), required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--duration', type=int, default=240)
    args = parser.parse_args()
    if not args.apply or os.environ.get('LINE_TEMPORARY_CUTOVER_ENABLED') != 'yes':
        raise SystemExit('Not authorized: both --apply and temporary cutover gate required')
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
    if not token:
        raise SystemExit('LINE access token unavailable; no mutation performed')
    signal.signal(signal.SIGINT, _cancel)
    signal.signal(signal.SIGTERM, _cancel)
    try:
        if args.action == 'trial':
            trial(token, args.duration)
        else:
            restore(token)
    except KeyboardInterrupt:
        raise SystemExit('Trial interrupted; check rollback verification') from None
    except Exception as exc:
        print(f'CUTOVER_BLOCKED_OR_FAILED: {exc}', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
