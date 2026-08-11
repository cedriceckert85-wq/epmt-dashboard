"""Doctor: real-project checks pass, unavailable provider CLIs are
UNVERIFIED (not silently OK, not fatally BLOCKED), version drift blocks."""
from pathlib import Path

from orchestrator.adapters.codex import CodexAdapter
from orchestrator.doctor import run_doctor, detect_capabilities

ROOT = Path(__file__).resolve().parents[2]


def _by_name(checks):
    return {c["name"]: c for c in checks}


def test_doctor_on_real_project_is_healthy():
    checks, caps, blocked = run_doctor(ROOT)
    by = _by_name(checks)
    for name in ("python", "git", "config", "canonical_state",
                 "test_registry", "schemas", "fake_agent"):
        assert by[name]["status"] == "OK", by[name]
    assert not blocked
    assert "none" in caps


def test_unavailable_provider_cli_is_unverified_not_blocked():
    checks, _, blocked = run_doctor(
        ROOT, adapters=(CodexAdapter("definitely-not-a-real-cli-xyz"),))
    by = _by_name(checks)
    assert by["adapter_codex"]["status"] == "UNVERIFIED"
    assert not blocked


def test_phase_requirement_scoping_reports_unverified_capabilities():
    checks, caps, _ = run_doctor(ROOT, phase_id="08")   # soak needs gpu/obs/...
    by = _by_name(checks)
    entry = by["phase_08_requirements"]
    if {"gpu", "obs", "riot_live", "tailscale", "network"} <= caps:
        assert entry["status"] == "OK"
    else:
        assert entry["status"] == "UNVERIFIED"
        assert "never skipped-as-pass" in entry["detail"]


def test_assumed_capabilities_are_honored():
    caps = detect_capabilities(assume=("obs", "gpu"))
    assert {"obs", "gpu", "none"} <= caps
