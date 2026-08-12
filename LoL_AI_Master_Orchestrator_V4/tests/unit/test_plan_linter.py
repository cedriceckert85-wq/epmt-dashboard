"""The plan linter runs inside the Phase-00 self-check, so any structural
contradiction in the shipped plan (ungated produced metric, deferrable
release test, prompt-only dependency, circular phase input, quality gate
that can auto-approve) fails the gate before a single agent runs."""
from pathlib import Path

from orchestrator.plan_linter import lint

ROOT = Path(__file__).resolve().parents[2]


def test_shipped_plan_has_no_structural_violations():
    violations = lint(ROOT)
    assert violations == [], "plan linter violations:\n" + "\n".join(violations)


def test_linter_catches_ungated_produced_metric(tmp_path):
    # build a tiny fake plan with a produced-but-ungated metric
    import yaml
    (tmp_path / "phases").mkdir()
    (tmp_path / "phases" / "phase-00.yaml").write_text(yaml.safe_dump({
        "id": "00", "name": "x", "builder": "claude", "reviewer": "codex",
        "required_tests": ["t"], "allowed_write_paths": ["reports/"],
        "depends_on": [], "metrics": []}), encoding="utf-8")
    (tmp_path / "test_registry.yaml").write_text(yaml.safe_dump({"tests": {"t": {
        "command": "python -c \"print(1)\"", "timeout_s": 10, "parser": "metrics_json",
        "evidence": "e.json", "implemented_in_phase": "00",
        "produces_metrics": ["ghost_metric"]}}}), encoding="utf-8")
    violations = lint(tmp_path)
    assert any("ghost_metric" in v and "gated by no phase" in v for v in violations)
