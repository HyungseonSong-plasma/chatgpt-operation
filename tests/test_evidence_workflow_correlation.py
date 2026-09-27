import pathlib


def test_evidence_workflow_exposes_durable_dispatch_identity():
    text=pathlib.Path(".github/workflows/samuel-evidence-acquisition.yml").read_text()
    assert "samuel_dispatch_id:" in text
    assert "required: true" in text
    assert "Samuel Evidence Acquisition dispatch:" in text
    assert "${{ inputs.samuel_dispatch_id }}" in text
