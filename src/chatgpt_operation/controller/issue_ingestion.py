"""Fail-closed admission of GitHub issues into Samuel's durable work ledger."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json
from typing import Any

ADMISSION_MARKER = "<!-- samuel-work-admission -->"
SCHEMA_VERSION = 1
ADMISSION_LABEL = "samuel"

class AdmissionError(ValueError):
    pass

@dataclass(frozen=True)
class AdmittedIssueWork:
    work_id: str
    issue_number: int
    title: str
    body: str
    html_url: str
    status: str = "admitted"

    @classmethod
    def from_issue(cls, issue: dict[str, Any]) -> "AdmittedIssueWork":
        number=issue.get("number")
        if not isinstance(number,int) or number <= 0:
            raise AdmissionError("issue number is required")
        labels={x.get("name") for x in issue.get("labels",[]) if isinstance(x,dict)}
        if ADMISSION_LABEL not in labels:
            raise AdmissionError("issue is not explicitly admitted")
        if issue.get("pull_request") is not None:
            raise AdmissionError("pull requests cannot enter the issue work queue")
        title=issue.get("title")
        if not isinstance(title,str) or not title.strip():
            raise AdmissionError("issue title is required")
        return cls(
            work_id=f"issue:{number}",
            issue_number=number,
            title=title.strip(),
            body=str(issue.get("body") or ""),
            html_url=str(issue.get("html_url") or ""),
        )

def decode_admission_ledger(body: str) -> dict[str, dict[str, Any]]:
    if ADMISSION_MARKER not in body:
        raise AdmissionError("admission marker missing")
    start=body.find("~~~json")
    end=body.find("~~~",start+7)
    if start < 0 or end < 0:
        raise AdmissionError("admission ledger JSON fence missing")
    raw=json.loads(body[start+7:end].strip())
    if raw.get("schema_version") != SCHEMA_VERSION or not isinstance(raw.get("work"),dict):
        raise AdmissionError("invalid admission ledger")
    return dict(raw["work"])

def encode_admission_ledger(work: dict[str, dict[str, Any]]) -> str:
    payload={"schema_version":SCHEMA_VERSION,"work":work}
    return ADMISSION_MARKER+"\n~~~json\n"+json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n~~~"

def admit_issue(comments: list[dict[str,Any]], issue: dict[str,Any]) -> dict[str,Any]:
    matches=[c for c in comments if ADMISSION_MARKER in str(c.get("body",""))]
    if len(matches)>1:
        raise AdmissionError("multiple authoritative admission ledgers")
    current={} if not matches else decode_admission_ledger(str(matches[0]["body"]))
    item=AdmittedIssueWork.from_issue(issue)
    existing=current.get(item.work_id)
    encoded=asdict(item)
    if existing is not None and existing != encoded:
        raise AdmissionError("admitted issue identity changed")
    current[item.work_id]=encoded
    return {
        "changed": existing is None,
        "comment_id": None if not matches else int(matches[0]["id"]),
        "body": encode_admission_ledger(current),
        "work_id": item.work_id,
    }
