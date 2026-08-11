"""Deterministic test runner: parsers, evidence verification, UNVERIFIED
for unmet requirements, 'exit 0 but no tests ran' can never pass."""
import textwrap
from pathlib import Path

from orchestrator.testexec import run_required_tests, _parse_junit

JUNIT_OK = '<testsuite tests="3" failures="0" errors="0" skipped="0"/>'
JUNIT_EMPTY = '<testsuite tests="0" failures="0" errors="0" skipped="0"/>'
JUNIT_ALL_SKIPPED = '<testsuite tests="2" failures="0" errors="0" skipped="2"/>'
JUNIT_FAIL = '<testsuite tests="3" failures="1" errors="0" skipped="0"/>'


def _registry(cmd, parser="exit_code", requires=("none",), evidence="ev.json", timeout=30):
    return {"t1": {"command": cmd, "cwd": ".", "timeout_s": timeout,
                   "requires": list(requires), "parser": parser,
                   "evidence": evidence, "implemented_in_phase": "00",
                   "produces_metrics": []}}


PHASE = {"id": "00", "required_tests": ["t1"]}


def test_exit_code_pass_and_fail(tmp_path):
    codes, _, out = run_required_tests(PHASE, _registry("python -c \"raise SystemExit(0)\""),
                                       run_id="r", workdir=tmp_path)
    assert codes["t1"] == 0 and out[0].status == "pass"
    codes, _, out = run_required_tests(PHASE, _registry("python -c \"raise SystemExit(3)\""),
                                       run_id="r", workdir=tmp_path)
    assert codes["t1"] == 3 and out[0].status == "fail"


def test_unmet_requirement_is_unverified_never_pass(tmp_path):
    codes, _, out = run_required_tests(
        PHASE, _registry("python -c \"raise SystemExit(0)\"", requires=("network",)),
        run_id="r", workdir=tmp_path, capabilities={"none"})
    assert codes["t1"] is None
    assert out[0].status == "unverified"
    assert "network" in out[0].detail


def test_unknown_registry_test_is_unverified(tmp_path):
    codes, _, out = run_required_tests(PHASE, {}, run_id="r", workdir=tmp_path)
    assert codes["t1"] is None and out[0].status == "unverified"


def test_exit_zero_without_junit_tests_fails(tmp_path):
    # command exits 0 AND writes junit claiming zero executed tests
    script = tmp_path / "w.py"
    script.write_text(textwrap.dedent(f"""
        import pathlib
        pathlib.Path("ev.xml").write_text('{JUNIT_EMPTY}')
    """))
    codes, _, out = run_required_tests(
        PHASE, _registry("python w.py", parser="pytest_junit", evidence="ev.xml"),
        run_id="r", workdir=tmp_path)
    assert codes["t1"] != 0 and out[0].status == "fail"
    assert "no executed tests" in out[0].detail


def test_junit_parser_matrix(tmp_path):
    for xml, ok in ((JUNIT_OK, True), (JUNIT_EMPTY, False),
                    (JUNIT_ALL_SKIPPED, False), (JUNIT_FAIL, False)):
        p = tmp_path / "j.xml"
        p.write_text(xml)
        got, _ = _parse_junit(p)
        assert got is ok
    assert _parse_junit(tmp_path / "missing.xml")[0] is False


def test_metrics_json_parser_feeds_gate_metrics(tmp_path):
    script = tmp_path / "m.py"
    script.write_text(
        'import json,pathlib; pathlib.Path("ev.json").write_text('
        'json.dumps({"metrics": {"sync_error_p95_ms": 12}}))')
    codes, metrics, out = run_required_tests(
        PHASE, _registry("python m.py", parser="metrics_json", evidence="ev.json"),
        run_id="r", workdir=tmp_path)
    assert codes["t1"] == 0 and metrics == {"sync_error_p95_ms": 12}


def test_metrics_json_missing_evidence_fails(tmp_path):
    codes, metrics, out = run_required_tests(
        PHASE, _registry("python -c \"raise SystemExit(0)\"",
                         parser="metrics_json", evidence="missing.json"),
        run_id="r", workdir=tmp_path)
    assert codes["t1"] != 0 and out[0].status == "fail"


def test_command_timeout_fails_closed(tmp_path):
    codes, _, out = run_required_tests(
        PHASE, _registry("python -c \"import time; time.sleep(60)\"", timeout=1),
        run_id="r", workdir=tmp_path)
    assert codes["t1"] != 0 and out[0].status == "fail"
    assert "timeout" in out[0].detail
