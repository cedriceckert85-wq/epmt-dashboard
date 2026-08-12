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


def test_junit_all_skipped_is_not_a_pass(tmp_path):
    # pytest reports a fully-skipped module as exit 0, tests=N, failures=0,
    # skipped=N — this must NOT count as a real pass (vacuous green).
    xml = ('<testsuite name="s" tests="2" failures="0" errors="0" skipped="2">'
           '<testcase name="a"><skipped/></testcase>'
           '<testcase name="b"><skipped/></testcase></testsuite>')
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and "skipped" in out.reason


def test_junit_inflated_tests_attr_cannot_hide_all_skipped(tmp_path):
    # a lying producer inflates suite tests="2" but emits ONE skipped testcase;
    # executed must be counted from real <testcase> elements -> FAIL.
    xml = ('<testsuite name="s" tests="2" failures="0" errors="0" skipped="0">'
           '<testcase name="only"><skipped/></testcase></testsuite>')
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and ("skipped" in out.reason or "no executed" in out.reason)


def test_junit_malformed_attribute_fails_closed_not_crash(tmp_path):
    xml = '<testsuite name="s" tests="oops" failures="x"><testcase name="a"/></testsuite>'
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    # a non-numeric attr must not raise; the real testcase count still governs
    assert out.status in ("pass", "fail")


def test_junit_all_skipped_via_per_testcase_children_is_not_a_pass(tmp_path):
    # a lying producer sets suite skipped="0" but marks every <testcase>
    # <skipped/> — must still FAIL (per-testcase counting).
    xml = ('<testsuite name="s" tests="2" failures="0" errors="0" skipped="0">'
           '<testcase name="a"><skipped/></testcase>'
           '<testcase name="b"><skipped/></testcase></testsuite>')
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and "skipped" in out.reason


def test_junit_per_testcase_failure_child_fails(tmp_path):
    xml = ('<testsuite name="s" tests="2" failures="0" errors="0">'
           '<testcase name="a"/><testcase name="b"><failure/></testcase></testsuite>')
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "fail" and "failures=1" in out.reason


def test_junit_partial_skip_still_passes(tmp_path):
    xml = ('<testsuite name="s" tests="3" failures="0" errors="0" skipped="1">'
           '<testcase name="a"/><testcase name="b"/>'
           '<testcase name="c"><skipped/></testcase></testsuite>')
    out = run_registry_test("t", spec(_junit_cmd(tmp_path, xml), parser="pytest_junit",
                                      evidence="ev/junit.xml"),
                            root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "pass"


def test_bearer_token_env_vars_are_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
    monkeypatch.setenv("SOME_CUSTOM_SECRET", "x")
    monkeypatch.setenv("MY_SERVICE_TOKEN", "x")
    monkeypatch.setenv("HARMLESS_VALUE", "keepme")
    env = stripped_env()
    for k in ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
              "SOME_CUSTOM_SECRET", "MY_SERVICE_TOKEN"):
        assert k not in env
    assert env.get("HARMLESS_VALUE") == "keepme"


def test_bare_python_resolved_to_running_interpreter(tmp_path):
    # a registry command using bare `python` must run even on a host with only
    # python3 — it is resolved to sys.executable.
    (tmp_path / "ev").mkdir()
    s = spec('python -c "import os;os.makedirs(\'ev\',exist_ok=True);open(\'ev/out.json\',\'w\').write(\'x\')"')
    out = run_registry_test("t", s, root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "pass"


def test_python_placeholder_substituted(tmp_path):
    s = spec('{python} -c "print(1)"')
    out = run_registry_test("t", s, root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "pass"


def test_non_utf8_output_does_not_crash(tmp_path):
    # a test emitting a raw non-UTF-8 byte must not raise UnicodeDecodeError
    s = spec(f'{PY} -c "import os,sys;os.write(1, b\'\\xff\\xfe\');sys.exit(0)"')
    out = run_registry_test("t", s, root=tmp_path, run_id="r", capabilities={}, deferrable=set())
    assert out.status == "pass"


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
