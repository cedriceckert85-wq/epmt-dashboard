"""Soak harness smoke: seeded run holds every invariant and emits
metrics evidence in the registry format."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_soak_iterations_hold_invariants(tmp_path):
    out = tmp_path / "soak.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "soak" / "run_8h_soak.py"),
         "--iterations", "400", "--json", str(out)],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text())
    m = data["metrics"]
    assert m["soak_iterations"] == 400
    assert m["invariant_violations"] == 0
    assert m["gate_false_passes"] == 0
    assert m["gate_false_blocks"] == 0
    assert m["state_corruptions"] == 0


def test_soak_is_seed_deterministic(tmp_path):
    outs = []
    for i in range(2):
        out = tmp_path / f"s{i}.json"
        subprocess.run(
            [sys.executable, str(ROOT / "tests" / "soak" / "run_8h_soak.py"),
             "--iterations", "150", "--seed", "42", "--json", str(out)],
            capture_output=True, text=True, timeout=300, check=True)
        outs.append(json.loads(out.read_text())["metrics"])
    assert outs[0] == outs[1]
