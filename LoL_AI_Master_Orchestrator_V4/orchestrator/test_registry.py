"""Loader/validator for test_registry.yaml — the mapping from every
symbolic required_test to a concrete command, timeout, requirements,
parser and evidence artifact. The gate engine only trusts exit codes and
metrics that originate from registry-executed commands.
"""
from pathlib import Path

import yaml

VALID_PARSERS = {"exit_code", "pytest_junit", "metrics_json"}
VALID_REQUIRES = {"none", "gpu", "windows", "tailscale", "riot_live", "obs",
                  "network", "real_stream", "long_run"}


def load(path="test_registry.yaml"):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    errors = []
    tests = data.get("tests", {})
    for tid, spec in tests.items():
        for key in ("command", "timeout_s", "parser", "evidence", "implemented_in_phase"):
            if key not in spec:
                errors.append(f"{tid}: missing {key}")
        if spec.get("parser") not in VALID_PARSERS:
            errors.append(f"{tid}: invalid parser {spec.get('parser')}")
        for r in spec.get("requires", ["none"]):
            if r not in VALID_REQUIRES:
                errors.append(f"{tid}: invalid requirement {r}")
        if not isinstance(spec.get("timeout_s"), int) or spec.get("timeout_s", 0) <= 0:
            errors.append(f"{tid}: timeout_s must be positive int")
    if errors:
        raise ValueError("test_registry invalid: " + "; ".join(errors))
    return tests


def coverage_gaps(tests, phases_dir="phases"):
    """Symbolic tests referenced by phase configs but absent from the
    registry. Must be empty — an unmapped test can never produce a
    trustworthy exit code."""
    missing = set()
    for p in sorted(Path(phases_dir).glob("phase-*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        for t in d.get("required_tests", []):
            if t not in tests:
                missing.add(f"{p.name}:{t}")
    return sorted(missing)


def unmet_requirements(spec, capabilities):
    """Requirements of a registry entry that the current host cannot satisfy."""
    reqs = [r for r in spec.get("requires", ["none"]) if r != "none"]
    return [r for r in reqs if not capabilities.get(r, False)]
