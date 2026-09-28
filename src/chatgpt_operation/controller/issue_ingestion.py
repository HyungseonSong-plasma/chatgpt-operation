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


def _label_names(issue: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in issue.get("labels", []):
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            value = item.get("name")
        else:
            continue
        if isinstance(value, str) and value:
            names.add(value)
    return names


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
        if ADMISSION_LABEL not in _label_names(issue):
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


def _upsert_admitted_issue(
    current: dict[str, dict[str, Any]],
    issue: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], str, bool]:
    updated={key:dict(value) for key,value in current.items()}
    item=AdmittedIssueWork.from_issue(issue)
    existing=updated.get(item.work_id)
    encoded=asdict(item)
    if existing is not None:
        if not encoded.get("html_url") and existing.get("html_url"):
            encoded["html_url"]=existing["html_url"]
        immutable=("work_id","issue_number","title","body","html_url")
        if any(existing.get(key) != encoded.get(key) for key in immutable):
            raise AdmissionError("admitted issue identity changed")
        encoded["status"]=existing.get("status","admitted")
    updated[item.work_id]=encoded
    return updated,item.work_id,existing is None


def discover_admissible_issues(
    current: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Admit explicit Samuel opt-ins discovered during any controller wake."""
    updated={key:dict(value) for key,value in current.items()}
    ordered=sorted(
        (item for item in issues if isinstance(item,dict)),
        key=lambda item: int(item.get("number",0))
        if isinstance(item.get("number"),int) else 0,
    )
    for issue in ordered:
        if issue.get("state") not in {None,"open"}:
            continue
        if ADMISSION_LABEL not in _label_names(issue):
            continue
        updated,_,_=_upsert_admitted_issue(updated,issue)
    return updated

def decode_admission_ledger(body: str) -> dict[str, dict[str, Any]]:
    if ADMISSION_MARKER not in body:
        raise AdmissionError("admission marker missing")
    start=body.find("~~~json")
    end=body.rfind("~~~")
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
    current,work_id,changed=_upsert_admitted_issue(current,issue)
    return {
        "changed": changed,
        "comment_id": None if not matches else int(matches[0]["id"]),
        "body": encode_admission_ledger(current),
        "work_id": work_id,
    }


def transition_issue_status(
    work: dict[str, dict[str, Any]], work_id: str, status: str
) -> dict[str, dict[str, Any]]:
    allowed={"admitted","reasoning_required","planned","active","complete","blocked","revision_required"}
    if status not in allowed:
        raise AdmissionError("unsupported issue lifecycle status")
    if work_id not in work:
        raise AdmissionError("unknown admitted issue")
    updated={key:dict(value) for key,value in work.items()}
    updated[work_id]["status"]=status
    return updated
