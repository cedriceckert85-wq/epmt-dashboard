from pathlib import Path

from orchestrator import test_registry
from orchestrator.config import load_config, load_phase, list_phase_ids

ROOT = Path(__file__).resolve().parents[2]


def test_registry_loads_and_is_valid():
    tests = test_registry.load(ROOT / "test_registry.yaml")
    assert len(tests) >= 40


def test_registry_covers_all_phase_tests():
    tests = test_registry.load(ROOT / "test_registry.yaml")
    assert test_registry.coverage_gaps(tests, ROOT / "phases") == []


def test_all_phase_files_exist_and_load():
    for i in range(21):
        assert (ROOT / "phases" / f"phase-{i:02d}.yaml").exists()
        load_phase(ROOT, f"{i:02d}")


def test_config_loads():
    cfg = load_config(ROOT)
    assert cfg.gate_mode in ("auto", "strict")
    assert "orchestrator" in cfg.immutable_paths
    assert "prompts" in cfg.immutable_paths


def test_phase_ids_sequential():
    ids = list_phase_ids(ROOT)
    assert ids == [f"{i:02d}" for i in range(21)]


def test_deferrable_tests_are_subset_of_required():
    for pid in list_phase_ids(ROOT):
        ph = load_phase(ROOT, pid)
        assert set(ph.get("deferrable_tests", [])) <= set(ph["required_tests"])


def test_hardware_tests_are_deferrable_where_required():
    """Every phase-required test with a hardware capability must be
    deferrable, otherwise a one-shot run on a plain PC can never finish."""
    tests = test_registry.load(ROOT / "test_registry.yaml")
    hw = {"gpu", "windows", "tailscale", "riot_live", "obs", "real_stream", "long_run"}
    for pid in list_phase_ids(ROOT):
        ph = load_phase(ROOT, pid)
        for t in ph["required_tests"]:
            reqs = set(tests[t].get("requires", [])) & hw
            if reqs:
                assert t in ph.get("deferrable_tests", []), (pid, t, reqs)


def test_review_prompt_files_exist():
    for pid in list_phase_ids(ROOT):
        ph = load_phase(ROOT, pid)
        for rel in ph.get("review_prompts", []):
            assert (ROOT / rel).exists(), rel


def test_unmet_requirements_helper():
    spec = {"requires": ["gpu", "network"]}
    assert test_registry.unmet_requirements(spec, {"network": True}) == ["gpu"]
    assert test_registry.unmet_requirements(spec, {"gpu": True, "network": True}) == []


def test_phase_selection_validation():
    from orchestrator.main import _parse_phase_selection
    from orchestrator.config import ConfigError
    import pytest
    ids = [f"{i:02d}" for i in range(21)]
    assert _parse_phase_selection("03-05", ids) == ["03", "04", "05"]
    assert _parse_phase_selection("02,04", ids) == ["02", "04"]
    assert _parse_phase_selection(None, ids) == ids
    for bad in ("05-03", "05-", "-05", "99", "99-100", "xx"):
        with pytest.raises(ConfigError):
            _parse_phase_selection(bad, ids)
