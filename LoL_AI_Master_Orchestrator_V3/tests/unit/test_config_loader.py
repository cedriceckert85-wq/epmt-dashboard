"""Config loader: real config valid, incomplete configs fail closed."""
import shutil
from pathlib import Path

import pytest

from orchestrator.config import Config, ConfigError

ROOT = Path(__file__).resolve().parents[2]


def test_real_config_loads():
    cfg = Config.load(ROOT)
    assert cfg.main_branch == "main"
    assert cfg.max_fix_cycles == 2
    assert 75 in cfg.retryable_exit_codes
    assert "state" in cfg.immutable_paths
    assert cfg.strip_test_secrets is True


def test_missing_file_fails(tmp_path):
    with pytest.raises(ConfigError, match="missing"):
        Config.load(tmp_path)


def test_invalid_yaml_fails(tmp_path):
    (tmp_path / "ORCHESTRATOR_CONFIG.yaml").write_text("a: [unclosed")
    with pytest.raises(ConfigError, match="YAML"):
        Config.load(tmp_path)


def test_missing_top_level_key_fails(tmp_path):
    (tmp_path / "ORCHESTRATOR_CONFIG.yaml").write_text("version: 2\nproject: {}\n")
    with pytest.raises(ConfigError, match="incomplete"):
        Config.load(tmp_path)


def test_non_ff_merge_strategy_rejected(tmp_path):
    text = (ROOT / "ORCHESTRATOR_CONFIG.yaml").read_text()
    (tmp_path / "ORCHESTRATOR_CONFIG.yaml").write_text(
        text.replace("merge_strategy: ff-only", "merge_strategy: merge"))
    with pytest.raises(ConfigError, match="merge_strategy"):
        Config.load(tmp_path)


def test_empty_immutable_paths_rejected(tmp_path):
    text = (ROOT / "ORCHESTRATOR_CONFIG.yaml").read_text()
    import yaml
    data = yaml.safe_load(text)
    data["security"]["immutable_paths"] = []
    (tmp_path / "ORCHESTRATOR_CONFIG.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigError, match="immutable_paths"):
        Config.load(tmp_path)
