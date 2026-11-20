"""Offline preflight for official LINE signed empty-event canary."""
import io
import json
import unittest

from scripts import line_gateway_canary as canary


class FakeReply(io.BytesIO):
    status=200
    def __init__(self,body):
        super().__init__(json.dumps(body).encode("utf-8"))


class GatewayCanaryTests(unittest.TestCase):
    def test_cannot_test_without_two_explicit_gates(self):
        calls=[]
        def opener(*args,**kwargs):
            calls.append(1)
            return FakeReply({"success": True,"statusCode":200})
        for apply,gate in ((False,"yes"),(False,""),(True,"")):
            with self.assertRaisesRegex(RuntimeError,"manual canary"):
                canary.run_canary("token",apply=apply,gate=gate,opener=opener)
        with self.assertRaisesRegex(RuntimeError,"TOKEN"):
            canary.run_canary("",apply=True,gate="yes",opener=opener)
        self.assertEqual(calls,[])

    def test_success_does_not_modify_registered_webhook(self):
        calls=[]
        def opener(request,timeout):
            calls.append((request,timeout))
            return FakeReply({"success":True,"statusCode":200,"detail":"do not log"})
        result=canary.run_canary("mock-only",apply=True,gate="yes",opener=opener)
        self.assertEqual(result["gateway"],"linestockgateway")
        self.assertTrue(result["signed_empty_event_accepted"])
        self.assertFalse(result["registered_endpoint_mutation_performed"])
        self.assertEqual(len(calls),1)
        request,timeout=calls[0]
        self.assertEqual(request.get_method(),"POST")
        self.assertEqual(request.full_url,canary.LINE_TEST_API)
        self.assertEqual(json.loads(request.data),{"endpoint":canary.GATEWAY_URL})
        self.assertEqual(timeout,25)
        self.assertNotIn("mock-only",str(result))
        self.assertNotIn("do not log",str(result))

    def test_rejected_canary_does_not_claim_success(self):
        for response in (
            {"success":False,"statusCode":503},
            {"success":True,"statusCode":401},
            {"statusCode":200},
        ):
            def opener(request,timeout):
                return FakeReply(response)
            with self.assertRaisesRegex(RuntimeError,"canary failed"):
                canary.run_canary("fake",apply=True,gate="yes",opener=opener)


if __name__=="__main__":
    unittest.main()
