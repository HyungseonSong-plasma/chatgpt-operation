import unittest

from chatgpt_operation.controller.issue_ingestion import (
    ADMISSION_MARKER, AdmissionError, admit_issue, decode_admission_ledger,
)

def issue(number=100, labels=("samuel",), title="Implement deterministic work"):
    return {
        "number": number,
        "title": title,
        "body": "Acceptance criteria",
        "html_url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": x} for x in labels],
    }

class IssueIngestionTests(unittest.TestCase):
    def test_admits_labeled_issue_with_deterministic_identity(self):
        write=admit_issue([],issue())
        self.assertTrue(write["changed"])
        self.assertEqual(write["work_id"],"issue:100")
        ledger=decode_admission_ledger(write["body"])
        self.assertEqual(ledger["issue:100"]["issue_number"],100)
        self.assertEqual(ledger["issue:100"]["status"],"admitted")

    def test_replay_is_noop(self):
        first=admit_issue([],issue())
        second=admit_issue([{"id":7,"body":first["body"]}],issue())
        self.assertFalse(second["changed"])
        self.assertEqual(second["comment_id"],7)
        self.assertEqual(second["body"],first["body"])

    def test_requires_explicit_samuel_label(self):
        with self.assertRaisesRegex(AdmissionError,"explicitly admitted"):
            admit_issue([],issue(labels=("bug",)))

    def test_rejects_changed_identity_after_admission(self):
        first=admit_issue([],issue())
        with self.assertRaisesRegex(AdmissionError,"identity changed"):
            admit_issue([{"id":7,"body":first["body"]}],issue(title="Changed title"))

    def test_enriches_legacy_empty_html_url_without_identity_failure(self):
        first=admit_issue([],issue())
        ledger=decode_admission_ledger(first["body"])
        ledger["issue:100"]["html_url"]=""
        legacy=ADMISSION_MARKER+"\n~~~json\n"+__import__("json").dumps(
            {"schema_version":1,"work":ledger},
            sort_keys=True,separators=(",",":"),
        )+"\n~~~"
        second=admit_issue([{"id":7,"body":legacy}],issue())
        self.assertTrue(second["changed"])
        enriched=decode_admission_ledger(second["body"])
        self.assertEqual(
            enriched["issue:100"]["html_url"],
            "https://github.com/o/r/issues/100",
        )

    def test_rejects_multiple_authoritative_ledgers(self):
        body=ADMISSION_MARKER+'\n~~~json\n{"schema_version":1,"work":{}}\n~~~'
        with self.assertRaisesRegex(AdmissionError,"multiple authoritative"):
            admit_issue([{"id":1,"body":body},{"id":2,"body":body}],issue())

    def test_admission_preserves_tilde_fences_inside_issue_body(self):
        item=issue()
        item["body"]="example\\n~~~json\\n{}\\n~~~\\n"
        write=admit_issue([],item)
        ledger=decode_admission_ledger(write["body"])
        self.assertEqual(ledger["issue:100"]["body"],item["body"])

if __name__ == "__main__":
    unittest.main()
