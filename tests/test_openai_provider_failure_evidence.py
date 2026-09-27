import io
import json
import unittest
from urllib import error

from chatgpt_operation.controller.openai_reasoning_provider import OpenAIReasoningProvider
from chatgpt_operation.controller.reasoning_provider import ProviderFailureKind, ProviderRequestFailure
from chatgpt_operation.controller.reasoning_qualification import QualificationCase, evaluate_shadow


def http_error(status, detail):
    return error.HTTPError(
        "https://api.openai.com/v1/responses", status, "x", {},
        io.BytesIO(json.dumps({"error": detail}).encode()),
    )


class OpenAIProviderFailureEvidenceTests(unittest.TestCase):
    def test_quota_429_is_nonretryable(self):
        p=OpenAIReasoningProvider("x",opener=lambda *a,**k: (_ for _ in ()).throw(
            http_error(429,{"type":"insufficient_quota","code":"insufficient_quota"})
        ))
        with self.assertRaises(ProviderRequestFailure) as cm:
            p.reason(task="x",context={},attempt=1,validation_error=None)
        self.assertEqual(cm.exception.kind,ProviderFailureKind.QUOTA_OR_BILLING)
        self.assertFalse(cm.exception.retryable)

    def test_rate_429_is_retryable(self):
        p=OpenAIReasoningProvider("x",opener=lambda *a,**k: (_ for _ in ()).throw(
            http_error(429,{"type":"rate_limit_error","code":"rate_limit_exceeded"})
        ))
        with self.assertRaises(ProviderRequestFailure) as cm:
            p.reason(task="x",context={},attempt=1,validation_error=None)
        self.assertEqual(cm.exception.kind,ProviderFailureKind.RATE_LIMITED)
        self.assertTrue(cm.exception.retryable)

    def test_shadow_preserves_safe_failure_evidence(self):
        p=OpenAIReasoningProvider("x",opener=lambda *a,**k: (_ for _ in ()).throw(
            http_error(429,{"type":"insufficient_quota","code":"insufficient_quota","message":"private detail"})
        ))
        r=evaluate_shadow(provider=p,case=QualificationCase("quota",{}))
        self.assertFalse(r.passed)
        self.assertFalse(r.executed)
        self.assertEqual(r.provider_failure["provider_code"],"insufficient_quota")
        self.assertNotIn("message",r.provider_failure)


if __name__=="__main__":
    unittest.main()
