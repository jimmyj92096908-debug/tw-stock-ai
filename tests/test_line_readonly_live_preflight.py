"""Non-mutating LINE release readiness preflight acceptance."""
import unittest

from scripts import line_readonly_live_preflight as preflight


class FakeReply:
    status = 200
    def __init__(self, url=preflight.GATEWAY_HEALTH_URL, status=200):
        self.url = url
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self.url


class LineReadOnlyPreflightTests(unittest.TestCase):
    def test_official_legacy_and_health_can_pass_but_cutover_never_approved(self):
        inspected = []
        def inspect(token):
            inspected.append(token)
            return {"active": True, "is_original_legacy_webhook": True}
        result = preflight.collect_preflight(
            "fake-token-never-real", inspector=inspect, health_probe=lambda: True
        )
        self.assertEqual(inspected, ["fake-token-never-real"])
        self.assertEqual(result["assessment"], "read_only_preflight_pass")
        self.assertTrue(result["legacy_webhook_active_and_original"])
        self.assertTrue(result["candidate_get_health_200"])
        for field in (
            "official_signed_empty_canary_performed",
            "official_signed_empty_canary_passed",
            "real_line_message_e2e_verified",
            "new_gateway_channel_secrets_present_verified",
            "new_gateway_enabled",
            "ready_for_cutover", "line_message_sent", "production_webhook_changed"
        ):
            self.assertIs(result[field], False)
        self.assertNotIn("fake-token-never-real", str(result))

    def test_missing_token_blocks_and_never_makes_official_request(self):
        count = []
        def inspect(_token):
            count.append(1)
            raise AssertionError("No official API should be called")
        result = preflight.collect_preflight(
            "", inspector=inspect, health_probe=lambda: True
        )
        self.assertEqual(count, [])
        self.assertEqual(result["assessment"], "blocked_or_inconclusive")
        self.assertEqual(result["blocker"], "official_read_token_missing")
        self.assertFalse(result["ready_for_cutover"])

    def test_unverified_webhook_or_inactive_legacy_blocks_release(self):
        for response in (
            {"active": False, "is_original_legacy_webhook": True},
            {"active": True, "is_original_legacy_webhook": False},
            {},
        ):
            result = preflight.collect_preflight(
                "mock", inspector=lambda _: response, health_probe=lambda: True
            )
            self.assertFalse(result["legacy_webhook_active_and_original"])
            self.assertEqual(result["assessment"], "blocked_or_inconclusive")
            self.assertEqual(result["blocker"], "registered_webhook_not_verified_original")

    def test_transport_exception_is_redacted(self):
        def inspect(_token):
            raise RuntimeError("Never show secret-or-message-contents")
        result = preflight.collect_preflight(
            "fake", inspector=inspect, health_probe=lambda: True
        )
        self.assertEqual(result["blocker"], "official_webhook_read_failed")
        self.assertNotIn("secret-or-message", str(result))

    def test_candidate_health_failure_cannot_be_called_ready(self):
        result = preflight.collect_preflight(
            "mock", inspector=lambda _:{
                "active":True,"is_original_legacy_webhook":True
            }, health_probe=lambda: False
        )
        self.assertEqual(result["blocker"], "candidate_health_check_failed")
        self.assertFalse(result["ready_for_cutover"])

    def test_candidate_probe_uses_only_public_get_without_any_auth_headers(self):
        requests=[]
        def opener(request, timeout):
            requests.append((request,timeout))
            return FakeReply()
        self.assertTrue(preflight.probe_candidate_health(opener=opener))
        self.assertEqual(len(requests),1)
        request,timeout=requests[0]
        self.assertEqual(request.get_method(),"GET")
        self.assertEqual(request.full_url,preflight.GATEWAY_HEALTH_URL)
        self.assertFalse(request.has_header("Authorization"))
        self.assertFalse(request.has_header("X-Line-Signature"))
        self.assertEqual(timeout,12)

    def test_redirected_candidate_health_is_not_accepted(self):
        redirected=preflight.probe_candidate_health(
            opener=lambda req,timeout: FakeReply(url="https://untrusted.example/health")
        )
        self.assertFalse(redirected)

    def test_preflight_does_not_mislabel_candidate_as_enabled(self):
        report=preflight.collect_preflight(
            "mock", inspector=lambda _:{"active":True,"is_original_legacy_webhook":True},
            health_probe=lambda:True
        )
        self.assertFalse(report["new_gateway_enabled"])
        self.assertFalse(report["new_gateway_channel_secrets_present_verified"])
        self.assertFalse(report["ready_for_cutover"])


if __name__ == "__main__":
    unittest.main()
