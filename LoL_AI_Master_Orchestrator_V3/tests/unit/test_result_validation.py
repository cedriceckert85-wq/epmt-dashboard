"""Structured-result validation: schema, extraction, report spoofing."""
from pathlib import Path

from orchestrator.models import AgentRequest, AgentRole
from orchestrator.result_validation import (
    extract_structured, load_schema, validate_agent_result)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = load_schema(ROOT / "schemas" / "agent_result.schema.json")


def _request(run_id="run-1", phase="00", role=AgentRole.BUILDER):
    return AgentRequest(run_id=run_id, phase_id=phase, role=role,
                        workspace=Path("."), prompt_file=Path("p.md"),
                        output_schema_file=Path("s.json"), timeout_s=10)


def _report(**over):
    base = {"run_id": "run-1", "phase_id": "00", "role": "builder",
            "status": "completed", "summary": "ok", "findings": [], "tests": []}
    base.update(over)
    return base


def test_valid_report_passes():
    assert validate_agent_result(_report(), schema=SCHEMA, request=_request()) == []


def test_missing_structured_fails():
    errs = validate_agent_result(None, schema=SCHEMA, request=_request())
    assert errs


def test_schema_invalid_fails():
    errs = validate_agent_result({"foo": "bar"}, schema=SCHEMA, request=_request())
    assert any("schema" in e for e in errs)


def test_report_spoofing_run_id_rejected():
    errs = validate_agent_result(_report(run_id="another-run"),
                                 schema=SCHEMA, request=_request())
    assert any("run_id" in e for e in errs)


def test_report_spoofing_phase_and_role_rejected():
    errs = validate_agent_result(_report(phase_id="07"),
                                 schema=SCHEMA, request=_request())
    assert any("phase_id" in e for e in errs)
    errs = validate_agent_result(_report(role="reviewer"),
                                 schema=SCHEMA, request=_request())
    assert any("role" in e for e in errs)


def test_duplicate_finding_ids_rejected():
    rep = _report(findings=[
        {"id": "F1", "severity": "low", "title": "a"},
        {"id": "F1", "severity": "low", "title": "b"}])
    errs = validate_agent_result(rep, schema=SCHEMA, request=_request())
    assert any("duplicate" in e for e in errs)


def test_extraction_plain_and_lastline_and_fenced_and_envelope():
    obj = '{"run_id":"r","phase_id":"00","role":"builder","status":"completed","summary":"s","findings":[],"tests":[]}'
    assert extract_structured(obj)["run_id"] == "r"
    assert extract_structured("noise\nmore noise\n" + obj)["run_id"] == "r"
    assert extract_structured("```json\n" + obj + "\n```")["run_id"] == "r"
    envelope = '{"type":"result","result":"```json\\n' + obj.replace('"', '\\"') + '\\n```"}'
    assert extract_structured(envelope)["run_id"] == "r"
    assert extract_structured("{bad json") is None
    assert extract_structured("") is None
