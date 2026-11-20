"""Offline tests for the official LINE webhook read/rollback safety gates."""
import io
import json
import unittest
from unittest.mock import Mock

from scripts import line_webhook_control as control


class FakeReply(io.BytesIO):
    status = 200

    def __init__(self, value):
        super().__init__(json.dumps(value).encode("utf-8"))


def mock_opener(*responses):
    queue = list(responses)
    events = []

    def opened(request, timeout):
        events.append((request, timeout))
        return FakeReply(queue.pop(0))

    return opened, events


class LINEWebhookControlTests(unittest.TestCase):
    def test_read_current_legacy_endpoint_only_and_does_not_write(self):
        opener, events = mock_opener({
            "active": True, "endpoint": control.LEGACY_URL
        })
        result = control.inspect_endpoint("fake-not-a-real-token", opener=opener)
        self.assertTrue(result["active"])
        self.assertTrue(result["is_original_legacy_webhook"])
        self.assertEqual(result["endpoint_path"], "/")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0].get_method(), "GET")
        self.assertEqual(events[0][0].full_url, control.API)
        self.assertEqual(events[0][1], 15)

    def test_arbitrary_hosts_or_query_strings_are_not_mistaken_for_legacy(self):
        for target in (
            "https://example.invalid/",
            control.LEGACY_URL + "?secret=test",
            "http://" + control.LEGACY_URL.removeprefix("https://"),
            "https://br-purple-smoke-a1t9dmzz-linewebhook.compute.c-1.ap-southeast-1.aws.neon.tech.evil.invalid/",
        ):
            opener, events = mock_opener({"active": True, "endpoint": target})
            result = control.inspect_endpoint("fake", opener=opener)
            self.assertFalse(result["is_original_legacy_webhook"])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0][0].get_method(), "GET")

    def test_restore_refuses_without_two_explicit_gates(self):
        opener, events = mock_opener()
        for apply, gate in [(False, ""), (False, "yes"), (True, "")]:
            with self.assertRaisesRegex(RuntimeError, "Explicit --apply"):
                control.restore_original("fake", apply=apply, gate=gate, opener=opener)
        self.assertEqual(events, [])

    def test_restore_legacy_if_current_endpoint_different_and_verify_after(self):
        opener, events = mock_opener(
            {"active": True, "endpoint": "https://staging.example.invalid/webhook"},
            {},
            {"active": True, "endpoint": control.LEGACY_URL},
        )
        result = control.restore_original(
            "fake-token", apply=True, gate="yes", opener=opener
        )
        self.assertEqual(result["status"], "restored-original")
        self.assertEqual([request.get_method() for request, _ in events],
                         ["GET", "PUT", "GET"])
        self.assertEqual(
            json.loads(events[1][0].data.decode("utf-8")),
            {"endpoint": control.LEGACY_URL},
        )

    def test_original_active_is_noop_and_does_not_issue_put(self):
        opener, events = mock_opener({
            "active": True, "endpoint": control.LEGACY_URL
        })
        result = control.restore_original(
            "fake", apply=True, gate="yes", opener=opener
        )
        self.assertEqual(result["status"], "already-original")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0].get_method(), "GET")

    def test_failed_restore_does_not_claim_success(self):
        opener, events = mock_opener(
            {"active": True, "endpoint": "https://other.example.invalid"},
            {}, {"active": False, "endpoint": control.LEGACY_URL},
        )
        with self.assertRaisesRegex(RuntimeError, "not verified active"):
            control.restore_original(
                "fake", apply=True, gate="yes", opener=opener
            )

    def test_token_required_without_making_requests(self):
        opener, events = mock_opener()
        with self.assertRaisesRegex(RuntimeError, "token"):
            control.inspect_endpoint("", opener=opener)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
