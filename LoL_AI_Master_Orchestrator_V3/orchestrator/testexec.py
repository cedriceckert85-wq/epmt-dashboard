"""Deterministic test execution.

Every symbolic required_test of a phase is resolved through
test_registry.yaml and executed as a child process with a hard timeout
and a secret-stripped environment. PASS is derived ONLY from exit codes
plus parser-verified evidence — never from agent claims.

Parsers:
- exit_code:    exit 0 == pass
- pytest_junit: exit 0 AND junit XML evidence exists AND it records >0
                executed tests with 0 failures/errors (an "exit 0 but no
                tests ran" run can never pass)
- metrics_json: exit 0 AND evidence json exists AND carries {"metrics": {...}};
                metrics are fed to the gate

An unmet `requires` capability yields UNVERIFIED (exit code None) — the
gate treats that as failure; it is never skipped-as-pass.
"""
import shlex, sys
import xml.etree.ElementTree as ET
import json as _json
from dataclasses import dataclass, field
from pathlib import Path

from .process_runner import ProcessRunner
from .secure_env import env_for_tests


@dataclass
class TestOutcome:
    test_id: str
    exit_code: object          # int, or None for UNVERIFIED
    status: str                # "pass" | "fail" | "unverified"
    detail: str = ""
    evidence: str = ""
    metrics: dict = field(default_factory=dict)
    duration_s: float = 0.0


def _parse_junit(evidence_path):
    """Returns (ok, detail). ok only for >0 executed tests, 0 failures/errors."""
    try:
        tree = ET.parse(evidence_path)
    except (OSError, ET.ParseError) as e:
        return False, f"junit evidence unreadable: {e}"
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = failures = errors = skipped = 0
    for s in suites:
        tests += int(s.get("tests", 0))
        failures += int(s.get("failures", 0))
        errors += int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    executed = tests - skipped
    if executed <= 0:
        return False, f"junit reports no executed tests (tests={tests}, skipped={skipped})"
    if failures or errors:
        return False, f"junit reports failures={failures} errors={errors}"
    return True, f"junit: {executed} tests passed"


def _parse_metrics(evidence_path):
    try:
        data = _json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError) as e:
        return None, f"metrics evidence unreadable: {e}"
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None, "metrics evidence missing 'metrics' object"
    return metrics, "metrics ok"


def run_required_tests(phase, registry, *, run_id, workdir,
                       capabilities=frozenset({"none"}), base_env=None,
                       runner=None, journal=None):
    """Executes every required_test of `phase`. Returns
    (exit_codes: {test_id: int|None}, metrics: {...}, outcomes: [TestOutcome])."""
    import os
    runner = runner or ProcessRunner()
    env = env_for_tests(base_env if base_env is not None else dict(os.environ))
    exit_codes, metrics, outcomes = {}, {}, []

    for test_id in phase.get("required_tests", []):
        spec = registry.get(test_id)
        if spec is None:
            outcomes.append(TestOutcome(test_id, None, "unverified",
                                        "not in test registry"))
            exit_codes[test_id] = None
            continue

        unmet = [r for r in spec.get("requires", ["none"])
                 if r != "none" and r not in capabilities]
        if unmet:
            outcomes.append(TestOutcome(test_id, None, "unverified",
                                        "unmet requirements: " + ", ".join(unmet)))
            exit_codes[test_id] = None
            if journal:
                journal.append("test_unverified", test=test_id, unmet=unmet, run_id=run_id)
            continue

        cmd = spec["command"].replace("{run_id}", run_id)
        evidence = str(spec["evidence"]).replace("{run_id}", run_id)
        argv = shlex.split(cmd)
        if argv and argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        evidence_path = Path(workdir) / evidence
        evidence_path.parent.mkdir(parents=True, exist_ok=True)

        r = runner.run(argv, cwd=str(Path(workdir) / spec.get("cwd", ".")),
                       timeout_s=int(spec["timeout_s"]), env=env)
        detail = ""
        if r.timed_out or r.cleanup_incomplete:
            status, code = "fail", (r.exit_code if r.exit_code != 0 else -9)
            detail = "timeout" + (" + incomplete process-tree cleanup" if r.cleanup_incomplete else "")
        elif r.exit_code != 0:
            status, code = "fail", r.exit_code
            detail = f"exit {r.exit_code}"
        else:
            parser = spec["parser"]
            if parser == "exit_code":
                status, code, detail = "pass", 0, "exit 0"
            elif parser == "pytest_junit":
                ok, detail = _parse_junit(evidence_path)
                status, code = ("pass", 0) if ok else ("fail", 1)
            elif parser == "metrics_json":
                m, detail = _parse_metrics(evidence_path)
                if m is None:
                    status, code = "fail", 1
                else:
                    status, code = "pass", 0
                    metrics.update(m)
            else:
                status, code, detail = "fail", 1, f"unknown parser {parser}"

        outcomes.append(TestOutcome(test_id, code, status, detail,
                                    str(evidence_path), dict(metrics), r.duration_s))
        exit_codes[test_id] = code
        if journal:
            journal.append("test_executed", test=test_id, status=status,
                           exit_code=code, detail=detail, run_id=run_id,
                           duration_s=round(r.duration_s, 3))
    return exit_codes, metrics, outcomes
