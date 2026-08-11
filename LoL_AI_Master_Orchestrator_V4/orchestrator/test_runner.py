"""Deterministic test execution from test_registry.yaml.

- Commands run with provider secrets stripped from the environment.
- Unmet host capabilities => UNVERIFIED (never skipped-as-pass). If the
  phase lists the test under deferrable_tests, it is recorded as deferred
  and does not block the gate; otherwise it blocks.
- Evidence artifacts land under .orchestrator/artifacts/<run_id>/.
"""
import json
import os
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import TestOutcome
from .process_runner import ProcessRunner
from .test_registry import unmet_requirements

DEFAULT_STRIP_ENV = [
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "OPENAI_ORG_ID",
    "OPENAI_BASE_URL", "CODEX_API_KEY", "RIOT_API_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN", "GH_TOKEN", "TS_AUTHKEY", "TAILSCALE_AUTHKEY",
    "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "SLACK_TOKEN",
]

# any env var whose name contains one of these substrings is also stripped —
# defense in depth against provider/bearer creds leaking into agent-authored
# test processes (which are untrusted candidate code)
STRIP_SUBSTRINGS = ("TOKEN", "API_KEY", "APIKEY", "SECRET", "PASSWORD",
                    "PASSWD", "CREDENTIAL", "PRIVATE_KEY", "ACCESS_KEY",
                    "AUTH_KEY", "SESSION_KEY")


def stripped_env(extra_strip=()):
    env = dict(os.environ)
    explicit = set(DEFAULT_STRIP_ENV) | set(extra_strip)
    for k in list(env):
        ku = k.upper()
        if k in explicit or any(s in ku for s in STRIP_SUBSTRINGS):
            env.pop(k, None)
    return env


def _parse_junit_ok(evidence_path):
    """(ok, reason) — junit XML must exist and contain no failures/errors."""
    p = Path(evidence_path)
    if not p.exists():
        return False, "junit evidence file missing"
    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as e:
        return False, f"junit evidence unparseable: {e}"
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = failures = errors = skipped = 0
    for s in suites:
        tests += int(s.get("tests", 0))
        failures += int(s.get("failures", 0))
        errors += int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    if tests == 0:
        return False, "junit evidence contains zero collected tests"
    if failures or errors:
        return False, f"junit evidence has failures={failures} errors={errors}"
    # pytest counts skipped cases in `tests`; an all-skipped suite exits 0 with
    # zero failures but has proven NOTHING. A required gate test must actually
    # execute assertions — never accept a wholly-skipped suite as a pass.
    executed = tests - skipped
    if executed <= 0:
        return False, f"junit evidence has no executed tests ({skipped} skipped, 0 run)"
    return True, f"junit: {executed} executed, {skipped} skipped, 0 failures"


def _parse_metrics_json(evidence_path):
    """(metrics|None, reason)."""
    p = Path(evidence_path)
    if not p.exists():
        return None, "metrics evidence file missing"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"metrics evidence invalid: {e}"
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None, 'metrics evidence must be {"metrics": {...}}'
    bad = [k for k, v in metrics.items() if not isinstance(v, (int, float, bool))]
    if bad:
        return None, f"non-numeric metrics: {', '.join(bad)}"
    return metrics, "ok"


def run_registry_test(name, spec, *, root, run_id, capabilities, deferrable,
                      strip_env_extra=(), runner=None):
    """Execute one registry test and parse its evidence. Fail closed."""
    runner = runner or ProcessRunner()
    root = Path(root)

    unmet = unmet_requirements(spec, capabilities)
    if unmet:
        return TestOutcome(
            name=name, status="unverified", deferred=name in deferrable,
            reason=f"unmet host requirements: {', '.join(unmet)}")

    command = spec["command"].replace("{run_id}", run_id)
    evidence = str(spec["evidence"]).replace("{run_id}", run_id)
    evidence_abs = root / evidence
    evidence_abs.parent.mkdir(parents=True, exist_ok=True)
    # stale evidence must never satisfy a fresh run
    if evidence_abs.exists():
        try:
            evidence_abs.unlink()
        except OSError:
            pass

    cwd = root / spec.get("cwd", ".")
    argv = shlex.split(command, posix=(os.name != "nt"))
    res = runner.run(argv, cwd=cwd, timeout_s=int(spec["timeout_s"]),
                     env=stripped_env(strip_env_extra))

    if res.timed_out:
        return TestOutcome(name=name, status="fail", exit_code=res.exit_code,
                           reason=f"timeout after {spec['timeout_s']}s"
                                  + (" (cleanup incomplete)" if res.cleanup_incomplete else ""),
                           evidence=evidence, duration_s=res.duration_s)

    parser = spec["parser"]
    if parser == "exit_code":
        ok = res.exit_code == 0
        return TestOutcome(name=name, status="pass" if ok else "fail",
                           exit_code=res.exit_code,
                           reason="" if ok else f"exit code {res.exit_code}",
                           evidence=evidence, duration_s=res.duration_s)
    if parser == "pytest_junit":
        junit_ok, reason = _parse_junit_ok(evidence_abs)
        ok = res.exit_code == 0 and junit_ok
        return TestOutcome(name=name, status="pass" if ok else "fail",
                           exit_code=res.exit_code,
                           reason="" if ok else f"exit {res.exit_code}; {reason}",
                           evidence=evidence, duration_s=res.duration_s)
    if parser == "metrics_json":
        metrics, reason = _parse_metrics_json(evidence_abs)
        ok = res.exit_code == 0 and metrics is not None
        return TestOutcome(name=name, status="pass" if ok else "fail",
                           exit_code=res.exit_code, metrics=metrics or {},
                           reason="" if ok else f"exit {res.exit_code}; {reason}",
                           evidence=evidence, duration_s=res.duration_s)
    return TestOutcome(name=name, status="fail", exit_code=res.exit_code,
                       reason=f"unknown parser {parser}")


def run_phase_tests(phase, registry, *, root, run_id, capabilities, strip_env_extra=()):
    """Run all required tests of a phase. Returns (outcomes, exit_codes, metrics,
    deferred_names). exit_codes contains 0 only for real passes; deferred
    tests are excluded from exit_codes (gate handles them explicitly)."""
    deferrable = set(phase.get("deferrable_tests", []))
    outcomes = []
    exit_codes = {}
    metrics = {}
    deferred = []
    for name in phase.get("required_tests", []):
        spec = registry.get(name)
        if spec is None:
            outcomes.append(TestOutcome(name=name, status="unverified",
                                        reason="test not in registry"))
            exit_codes[name] = 1
            continue
        out = run_registry_test(name, spec, root=root, run_id=run_id,
                                capabilities=capabilities, deferrable=deferrable,
                                strip_env_extra=strip_env_extra)
        outcomes.append(out)
        if out.deferred:
            deferred.append(name)
        else:
            exit_codes[name] = out.as_exit_code()
        metrics.update(out.metrics)
    return outcomes, exit_codes, metrics, deferred
