"""Fake adapter through the real ProcessRunner: success, fail, timeout,
malformed, schema-invalid, retryable — the fault matrix every provider
adapter must survive."""
from pathlib import Path

from orchestrator.adapters.fake import FakeAdapter
from orchestrator.models import AgentRequest, AgentRole

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "fakes" / "fake_agent.py"


def _request(tmp_path, timeout=30):
    return AgentRequest(run_id="run-1", phase_id="00", role=AgentRole.BUILDER,
                        workspace=tmp_path, prompt_file=Path("p.md"),
                        output_schema_file=Path("s.json"), timeout_s=timeout)


def _run(tmp_path, mode, timeout=30):
    return FakeAdapter(SCRIPT, mode=mode, timeout_s=timeout).run(_request(tmp_path, timeout))


def test_success(tmp_path):
    r = _run(tmp_path, "success")
    assert r.exit_code == 0 and not r.timed_out
    assert r.structured["status"] == "completed"
    assert r.structured["run_id"] == "run-1"      # request binding honored


def test_fail(tmp_path):
    r = _run(tmp_path, "fail")
    assert r.exit_code == 2 and r.structured is None


def test_hang_is_killed_by_timeout(tmp_path):
    r = _run(tmp_path, "hang", timeout=1)
    assert r.timed_out and r.structured is None


def test_malformed_json(tmp_path):
    r = _run(tmp_path, "malformed")
    assert r.exit_code == 0 and r.structured is None


def test_schema_invalid_payload_extracted_but_invalid(tmp_path):
    from orchestrator.result_validation import load_schema, validate_agent_result
    r = _run(tmp_path, "schema-invalid")
    assert r.exit_code == 0 and r.structured == {"foo": "bar"}
    schema = load_schema(ROOT / "schemas" / "agent_result.schema.json")
    assert validate_agent_result(r.structured, schema=schema,
                                 request=_request(tmp_path))


def test_retryable_quota_exit(tmp_path):
    r = _run(tmp_path, "retryable")
    assert r.exit_code == 75


def test_doctor_reports_missing_script(tmp_path):
    d = FakeAdapter(tmp_path / "nope.py").doctor()
    assert d["available"] is False
