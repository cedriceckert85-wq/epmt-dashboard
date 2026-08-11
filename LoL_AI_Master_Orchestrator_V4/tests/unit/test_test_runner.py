import sys

from orchestrator.test_runner import (DEFAULT_STRIP_ENV, run_registry_test,
                                      stripped_env)

PY = sys.executable


def spec(command, parser="exit_code", evidence="ev/out.json", requires=None, timeout=60):
    return {"command": command, "cwd": ".", "timeout_s": timeout,
            "parser": parser, "evidence": evidence,
            "requires": requires or ["none"], "implemented_in_phase": "01"}


def test_exit_code_pass_and_fail(tmp_path):
    out = run_registry_test("t", spec(f'"{PY}" -c "print(1)"'), root=tmp_path,
                            run_id="r", capabilities={}, deferrable=set())
    assert out.status == "pass"
    out = run_registry_test("t", spec(f'"{PY}" -c "import sys;sys.exit(2)"'),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and out.as_exit_code() != 0


def test_unmet_requirement_unverified_and_deferral(tmp_path):
    s = spec(f'"{PY}" -c "print(1)"', requires=["gpu"])
    out = run_registry_test("t", s, root=tmp_path, run_id="r",
                            capabilities={"gpu": False}, deferrable=set())
    assert out.status == "unverified" and not out.deferred
    out = run_registry_test("t", s, root=tmp_path, run_id="r",
                            capabilities={"gpu": False}, deferrable={"t"})
    assert out.status == "unverified" and out.deferred
    # capability present => actually runs
    out = run_registry_test("t", s, root=tmp_path, run_id="r",
                            capabilities={"gpu": True}, deferrable=set())
    assert out.status == "pass"


def test_metrics_json_parsing(tmp_path):
    cmd = (f'"{PY}" -c "import json,os,sys;'
           f"os.makedirs('ev',exist_ok=True);"
           f"json.dump({{'metrics':{{'m1':1}}}},open('ev/out.json','w'))\"")
    out = run_registry_test("t", spec(cmd, parser="metrics_json"), root=tmp_path,
                            run_id="r", capabilities={}, deferrable=set())
    assert out.status == "pass" and out.metrics == {"m1": 1}


def test_metrics_json_missing_evidence_fails(tmp_path):
    out = run_registry_test("t", spec(f'"{PY}" -c "print(1)"', parser="metrics_json"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and "missing" in out.reason


def test_junit_parser_requires_real_evidence(tmp_path):
    # exit 0 but no junit file => fail closed (tests lying protection)
    out = run_registry_test("t", spec(f'"{PY}" -c "print(1)"', parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and "junit" in out.reason


def _junit_cmd(tmp_path, xml):
    """Command that copies pre-staged XML into the evidence path at run time
    (the runner deletes stale evidence before executing the command)."""
    (tmp_path / "junit_src.xml").write_text(xml, encoding="utf-8")
    script = tmp_path / "write_junit.py"
    script.write_text(
        "import os, shutil\n"
        "os.makedirs('ev', exist_ok=True)\n"
        "shutil.copyfile('junit_src.xml', 'ev/junit.xml')\n", encoding="utf-8")
    return f'"{PY}" "{script}"'


def test_junit_parser_accepts_green_suite(tmp_path):
    xml = ('<testsuite name="s" tests="2" failures="0" errors="0">'
           '<testcase name="a"/><testcase name="b"/></testsuite>')
    cmd = _junit_cmd(tmp_path, xml)
    out = run_registry_test("t", spec(cmd, parser="pytest_junit", evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "pass"


def test_junit_failures_fail(tmp_path):
    xml = ('<testsuite name="s" tests="2" failures="1" errors="0">'
           '<testcase name="a"/><testcase name="b"/></testsuite>')
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and "failures=1" in out.reason


def test_junit_zero_tests_fails(tmp_path):
    xml = '<testsuite name="s" tests="0" failures="0" errors="0"></testsuite>'
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and "zero" in out.reason


def test_env_stripping():
    env = stripped_env()
    for k in DEFAULT_STRIP_ENV:
        assert k not in env


def test_secrets_never_reach_test_processes(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret")
    cmd = f'"{PY}" -c "import os,sys;sys.exit(1 if os.environ.get(\'ANTHROPIC_API_KEY\') else 0)"'
    out = run_registry_test("t", spec(cmd), root=tmp_path, run_id="r",
                            capabilities={}, deferrable=set())
    assert out.status == "pass"
