"""Static plan linter — enforces the cross-file invariants whose violation
caused the review findings (ungated produced metrics, deferrable release
tests, prompt-only dependencies, circular phase inputs, human gates that can
auto-approve a subjective decision, dangling invalidated_by).

Run as part of the Phase-00 self-check (see tests/unit/test_plan_linter.py)
and available as `python -m orchestrator ... ` helpers. Returns a list of
human-readable violation strings; empty == clean.
"""
from pathlib import Path

import yaml

from .config import list_phase_ids, load_phase
from .test_registry import load as load_registry

# metrics that are observed/reported but intentionally NOT gated (none today)
OBSERVABILITY_ONLY = set()
HARDWARE_CAPS = {"gpu", "windows", "tailscale", "riot_live", "obs", "real_stream", "long_run"}
# phases whose subjective quality a real human must sign off for certification
EXPECTED_HUMAN_REVIEW = {"12", "14", "16", "20"}


def lint(root):
    root = Path(root)
    violations = []
    registry = load_registry(root / "test_registry.yaml")
    ids = list_phase_ids(root)
    phases = {pid: load_phase(root, pid) for pid in ids}

    parser_of = {t: s.get("parser") for t, s in registry.items()}
    produced_by = {}
    for t, s in registry.items():
        for m in (s.get("produces_metrics") or []):
            produced_by.setdefault(m, set()).add(t)

    # 1) every produced numeric metric is gated somewhere OR observability_only
    gated = set()
    for ph in phases.values():
        for rule in ph.get("metrics", []):
            gated.add(rule["name"])
    for m, producers in produced_by.items():
        if m not in gated and m not in OBSERVABILITY_ONLY:
            violations.append(
                f"metric '{m}' is produced by {sorted(producers)} but gated by no phase "
                f"and not marked observability_only")

    # 2) only metrics_json tests may declare produces_metrics
    for t, s in registry.items():
        if s.get("produces_metrics") and s.get("parser") != "metrics_json":
            violations.append(
                f"test '{t}' (parser {s.get('parser')}) declares produces_metrics it cannot emit")

    for pid, ph in phases.items():
        req = set(ph.get("required_tests", []))
        deferrable = set(ph.get("deferrable_tests", []))
        release_req = set(ph.get("release_required_tests", []))
        depends = ph.get("depends_on")

        # 3) every gate metric has an in-phase metrics_json producer
        for rule in ph.get("metrics", []):
            prod = {t for t in produced_by.get(rule["name"], set())
                    if t in req and parser_of.get(t) == "metrics_json"}
            if not prod:
                violations.append(
                    f"phase {pid}: gate metric '{rule['name']}' has no in-phase "
                    f"metrics_json producer (dead-end)")

        # 4) machine-enforced dependencies must exist (not prompt-only)
        if depends is None:
            violations.append(f"phase {pid}: missing machine-readable depends_on")
        else:
            for d in depends:
                if d not in phases:
                    violations.append(f"phase {pid}: depends_on unknown phase '{d}'")
                if d >= pid:
                    violations.append(
                        f"phase {pid}: depends_on '{d}' is not an earlier phase (would be circular)")

        # 5) every deferrable test that needs real hardware is release_required
        for t in deferrable:
            reqs = set(registry.get(t, {}).get("requires", [])) & HARDWARE_CAPS
            if reqs and t not in release_req:
                violations.append(
                    f"phase {pid}: '{t}' is deferrable + needs {sorted(reqs)} but is not in "
                    f"release_required_tests (would silently drop from certification)")

        # 6) release_required must be a subset of the phase's required tests
        for t in release_req:
            if t not in req:
                violations.append(f"phase {pid}: release_required '{t}' is not a required_test")

        # 7) invalidated_by references must be valid phases
        for d in ph.get("invalidated_by", []):
            if d not in phases:
                violations.append(f"phase {pid}: invalidated_by unknown phase '{d}'")

    # 8) the subjective quality gates are actually marked human_review_required
    for pid in EXPECTED_HUMAN_REVIEW:
        ph = phases.get(pid, {})
        if not ph.get("human_review_required"):
            violations.append(
                f"phase {pid}: expected a subjective quality gate but human_review_required is not set")
        if ph.get("human_review_required") and not ph.get("human_gate"):
            violations.append(
                f"phase {pid}: human_review_required but human_gate is false (cannot pause for a human)")

    return violations
