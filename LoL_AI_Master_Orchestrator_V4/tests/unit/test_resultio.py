import json

from orchestrator.resultio import read_agent_result, validate_agent_result


def good(**kw):
    base = {"run_id": "r1", "phase_id": "01", "role": "builder",
            "status": "completed", "summary": "did things",
            "findings": [], "tests": []}
    base.update(kw)
    return base


def test_valid_result():
    assert validate_agent_result(good(), expected_phase="01", expected_role="builder") == []


def test_missing_keys():
    probs = validate_agent_result({"summary": "x"}, expected_phase="01", expected_role="builder")
    assert any("missing key" in p for p in probs)


def test_role_and_phase_mismatch():
    probs = validate_agent_result(good(role="reviewer"), expected_phase="01",
                                  expected_role="builder")
    assert any("role mismatch" in p for p in probs)
    probs = validate_agent_result(good(phase_id="02"), expected_phase="01",
                                  expected_role="builder")
    assert any("phase mismatch" in p for p in probs)


def test_findings_need_stable_unique_ids():
    r = good(findings=[{"severity": "high", "title": "no id"}])
    probs = validate_agent_result(r, expected_phase="01", expected_role="builder")
    assert any("stable id" in p for p in probs)
    r = good(findings=[{"id": "F1", "severity": "high", "title": "a"},
                       {"id": "F1", "severity": "low", "title": "b"}])
    probs = validate_agent_result(r, expected_phase="01", expected_role="builder")
    assert any("duplicated" in p for p in probs)


def test_read_missing_file(tmp_path):
    res, probs = read_agent_result(tmp_path, expected_phase="01", expected_role="builder")
    assert res is None and probs


def test_read_valid_file(tmp_path):
    p = tmp_path / "reports" / "agent_result.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(good()), encoding="utf-8")
    res, probs = read_agent_result(tmp_path, expected_phase="01", expected_role="builder")
    assert probs == [] and res["status"] == "completed"
