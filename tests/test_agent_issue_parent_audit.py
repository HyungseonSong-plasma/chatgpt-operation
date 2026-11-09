"""Read-only parent audit and safe artifact redirect boundary tests."""
from __future__ import annotations

import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from chatgpt_operation.controller.agent_issue_artifact_download import (
    _allowed_download_host, authenticated_artifact_zip,
)
from chatgpt_operation.controller.agent_issue_attestation import AgentEvidenceError
from chatgpt_operation.controller.agent_issue_parent_audit import audit_all_agent_children


class FakeSignedZipResponse:
    def __init__(self,body=b"PK\x03\x04TEST",status=200):
        self.body=body
        self.status=status

    def __enter__(self):
        return self

    def __exit__(self,*_):
        pass

    def getcode(self):
        return self.status

    def read(self,amount):
        return self.body[:amount]


class FakeRedirectOpener:
    def __init__(self,target,body=b"PK\x03\x04TEST"):
        self.target=target
        self.body=body
        self.calls=[]

    def open(self,request,timeout=30):
        self.calls.append(request)
        if len(self.calls)==1:
            raise HTTPError(
                request.full_url,302,"Found",
                {"Location":self.target},None,
            )
        return FakeSignedZipResponse(self.body)


class ChildArtifactDownloadTests(unittest.TestCase):
    def test_signed_zip_is_downloaded_without_forwarding_github_api_token(self):
        url="https://productionresults.blob.core.windows.net/private/signed?sig=test"
        opener=FakeRedirectOpener(url)
        with patch(
            "chatgpt_operation.controller.agent_issue_artifact_download.build_opener",
            return_value=opener,
        ):
            data=authenticated_artifact_zip(
                repository="HyungseonSong-plasma/chatgpt-operation",
                artifact_id=123,token="super_secret",
            )
        self.assertEqual(data,b"PK\x03\x04TEST")
        first,second=opener.calls
        self.assertIn("Bearer super_secret",str(first.header_items()))
        self.assertNotIn("super_secret",str(second.header_items()))
        self.assertNotIn("Authorization",str(second.header_items()))
        self.assertEqual(second.full_url,url)

    def test_redirect_host_is_allowlisted_and_https_only(self):
        self.assertTrue(_allowed_download_host("objects.githubusercontent.com"))
        self.assertTrue(_allowed_download_host("productionresults.blob.core.windows.net"))
        self.assertFalse(_allowed_download_host("blob.core.windows.net.evil.com"))
        self.assertFalse(_allowed_download_host("attacker.example"))
        for url in (
            "http://productionresults.blob.core.windows.net/evil",
            "https://attacker.example/zip",
            "https://objects.githubusercontent.com.evil.com/zip",
        ):
            with self.subTest(url=url):
                opener=FakeRedirectOpener(url)
                with patch(
                    "chatgpt_operation.controller.agent_issue_artifact_download.build_opener",
                    return_value=opener,
                ):
                    with self.assertRaisesRegex(AgentEvidenceError,"not trusted CDN"):
                        authenticated_artifact_zip(
                            repository="HyungseonSong-plasma/chatgpt-operation",
                            artifact_id=1,token="token",
                        )
                self.assertEqual(len(opener.calls),1)

    def test_redirect_not_issued_and_oversized_zip_fail_closed(self):
        opener=FakeRedirectOpener(
            "https://objects.githubusercontent.com/signed",
            body=b"Z"*800001,
        )
        with patch(
            "chatgpt_operation.controller.agent_issue_artifact_download.build_opener",
            return_value=opener,
        ):
            with self.assertRaisesRegex(AgentEvidenceError,"size exceeded"):
                authenticated_artifact_zip(
                    repository="HyungseonSong-plasma/chatgpt-operation",
                    artifact_id=12,token="token",
                )


class ParentReadOnlyAuditTests(unittest.TestCase):
    def test_parent_without_allocation_emits_no_work_and_no_mutation(self):
        fake=object()
        with patch(
            "chatgpt_operation.controller.agent_issue_parent_audit.read_live_parent_registry",
            return_value=[],
        ),patch(
            "chatgpt_operation.controller.agent_issue_parent_audit.reduce_verified_parent_children",
        ) as reducer:
            result=audit_all_agent_children(transport=fake,token="read-only-token")
        self.assertEqual(result["status"],"NO_ALLOCATIONS")
        self.assertFalse(result["merge_authorized"])
        self.assertIsNone(result["parent_mutation"])
        reducer.assert_not_called()

    def test_parent_only_uses_live_read_verifier_and_does_not_merge(self):
        fake=object()
        allocation={"agent_id":"agent-a","child_issue":501}
        observed={
            "status":"READY_FOR_PARENT_REVIEW",
            "children":[{"child_issue":501}],
            "parent_mutation":None,"merge_authorized":False,
        }
        def probe_parent(*_,**kwargs):
            self.assertEqual(kwargs["registry"],[allocation])
            self.assertEqual(kwargs["live_gate_states"],{"attested-source":"PASS"})
            self.assertTrue(callable(kwargs["verify_source"]))
            return observed
        with patch(
            "chatgpt_operation.controller.agent_issue_parent_audit.read_live_parent_registry",
            return_value=[allocation],
        ),patch(
            "chatgpt_operation.controller.agent_issue_parent_audit.reduce_verified_parent_children",
            side_effect=probe_parent,
        ):
            result=audit_all_agent_children(transport=fake,token="readtoken")
        self.assertEqual(result["status"],"READY_FOR_PARENT_REVIEW")
        self.assertFalse(result["merge_authorized"])
        self.assertIsNone(result["parent_mutation"])


if __name__=="__main__":
    unittest.main()
