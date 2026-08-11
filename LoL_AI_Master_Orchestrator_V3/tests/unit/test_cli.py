"""CLI surface: status/doctor behave, run is gated fail-closed while
phase 00 is unpassed, bad invocations exit 2."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _cli(*args, timeout=180):
    return subprocess.run([sys.executable, "-m", "orchestrator.main", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def test_status_prints_canonical_state():
    r = _cli("status")
    assert r.returncode == 0
    st = json.loads(r.stdout)
    assert st["phase_id"] == "00" and st["lifecycle"] == "READY"


def test_doctor_json_reports_checks():
    r = _cli("doctor", "--json")
    data = json.loads(r.stdout)
    names = {c["name"] for c in data["checks"]}
    assert {"python", "git", "config", "canonical_state",
            "test_registry", "schemas", "fake_agent"} <= names
    # provider CLIs may be absent — that must yield UNVERIFIED, never a crash
    assert r.returncode in (0, 3)
    for c in data["checks"]:
        assert c["status"] in ("OK", "WARN", "UNVERIFIED", "BLOCKED")


def test_run_live_blocked_before_phase00_pass():
    r = _cli("run", "--phase", "01")
    assert r.returncode == 3
    assert "BLOCKED" in r.stderr or "BLOCKED" in r.stdout


def test_invalid_invocation_exits_2():
    r = _cli("approve", "--commit", "x", "--approver", "y",
             "--decision", "MAYBE")
    assert r.returncode == 2


def test_unknown_command_fails():
    r = _cli("frobnicate")
    assert r.returncode != 0
