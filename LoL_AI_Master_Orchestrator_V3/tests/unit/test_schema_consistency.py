import json, yaml
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def test_phase_ids_are_strings_and_two_digits():
    for p in (ROOT/"phases").glob("phase-*.yaml"):
        d=yaml.safe_load(p.read_text(encoding="utf-8"))
        assert isinstance(d["id"],str)
        assert len(d["id"])==2 and d["id"].isdigit()

def test_finding_schema_supports_review_fields_and_requires_id():
    s=json.loads((ROOT/"schemas/agent_result.schema.json").read_text(encoding="utf-8"))
    items=s["properties"]["findings"]["items"]
    props=items["properties"]
    for k in ["id","severity","title","evidence","reproduction","expected","actual","required_test"]:
        assert k in props
    assert set(items["required"])>= {"id","severity","title"}

def test_agent_schema_carries_no_acceptance_fields():
    s=json.loads((ROOT/"schemas/agent_result.schema.json").read_text(encoding="utf-8"))
    props=s["properties"]["findings"]["items"]["properties"]
    assert "accepted_by" not in props and "acceptance_reason" not in props and "accepted" not in props

def test_acceptance_record_schema_exists_and_binds_sha():
    s=json.loads((ROOT/"schemas/finding_acceptance.schema.json").read_text(encoding="utf-8"))
    assert set(s["required"])=={"phase_id","finding_id","commit_sha","decision","reason","approver","timestamp_utc"}
    assert s.get("additionalProperties") is False
