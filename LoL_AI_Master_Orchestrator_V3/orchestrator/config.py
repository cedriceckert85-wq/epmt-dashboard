"""Fail-closed loader/validator for ORCHESTRATOR_CONFIG.yaml.

Every consumer goes through Config so a missing/invalid key blocks at
startup instead of surfacing mid-phase. The config file itself is an
immutable path for agents; only humans may edit it.
"""
import yaml
from pathlib import Path


class ConfigError(Exception):
    pass


REQUIRED_TOP = (
    "version", "project", "agents", "retry", "security", "git",
    "human_gates", "acceptance", "test_registry", "gate_policy",
    "retryable_exit_codes", "path_policy",
)
REQUIRED_PROJECT = (
    "name", "main_branch", "canonical_state", "current_task", "journal",
    "generated_state_markdown", "generated_task_markdown",
    "worktree_root", "artifact_root", "lock_file",
)
REQUIRED_AGENT = ("executable", "timeout_s", "max_retries")
REQUIRED_RETRY = ("infrastructure_backoff_s", "invalid_schema_retries", "max_fix_cycles")

# Paths the orchestrator itself owns and mutates at the repo root. They are
# excluded from the "clean main" check (the orchestrator is the single
# writer for them); agents still may never touch them (immutable_paths).
ORCHESTRATOR_OWNED_PREFIXES = (
    "state/", "reports/", ".orchestrator/",
    "PROJECT_STATE.md", "CURRENT_TASK.md",
)


class Config:
    def __init__(self, data, root):
        self.data = data
        self.root = Path(root)

    @classmethod
    def load(cls, root, filename="ORCHESTRATOR_CONFIG.yaml"):
        p = Path(root) / filename
        try:
            raw = p.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise ConfigError(f"config missing: {p}") from e
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise ConfigError(f"config YAML invalid: {e}") from e
        if not isinstance(data, dict):
            raise ConfigError("config is not a mapping")

        missing = [k for k in REQUIRED_TOP if k not in data]
        if missing:
            raise ConfigError("config incomplete: missing " + ", ".join(missing))
        proj = data["project"]
        missing = [k for k in REQUIRED_PROJECT if k not in (proj or {})]
        if missing:
            raise ConfigError("config.project incomplete: missing " + ", ".join(missing))
        agents = data["agents"] or {}
        if not agents:
            raise ConfigError("config.agents empty")
        for name, agent in agents.items():
            miss = [k for k in REQUIRED_AGENT if k not in (agent or {})]
            if miss:
                raise ConfigError(f"config.agents.{name} incomplete: missing " + ", ".join(miss))
        retry = data["retry"] or {}
        miss = [k for k in REQUIRED_RETRY if k not in retry]
        if miss:
            raise ConfigError("config.retry incomplete: missing " + ", ".join(miss))
        if not isinstance(retry["infrastructure_backoff_s"], list):
            raise ConfigError("config.retry.infrastructure_backoff_s must be a list")
        sec = data["security"] or {}
        if not sec.get("immutable_paths"):
            raise ConfigError("config.security.immutable_paths missing/empty")
        if data["git"].get("merge_strategy") != "ff-only":
            raise ConfigError("unsupported merge_strategy (only ff-only is implemented)")
        return cls(data, root)

    # --- typed accessors -------------------------------------------------
    @property
    def main_branch(self): return self.data["git"].get("main_branch") or self.data["project"].get("main_branch")

    @property
    def require_clean_main(self): return bool(self.data["git"].get("require_clean_main", True))

    @property
    def agents_may_commit(self): return bool(self.data["git"].get("agents_may_commit", False))

    @property
    def state_path(self): return self.root / self.data["project"]["canonical_state"]

    @property
    def current_task_path(self): return self.root / self.data["project"]["current_task"]

    @property
    def journal_path(self): return self.root / self.data["project"]["journal"]

    @property
    def state_md_path(self): return self.root / self.data["project"]["generated_state_markdown"]

    @property
    def task_md_path(self): return self.root / self.data["project"]["generated_task_markdown"]

    @property
    def lock_path(self): return self.root / self.data["project"]["lock_file"]

    @property
    def worktree_root(self): return self.root / self.data["project"]["worktree_root"]

    @property
    def artifact_root(self): return self.root / self.data["project"]["artifact_root"]

    @property
    def immutable_paths(self): return tuple(self.data["security"]["immutable_paths"])

    @property
    def strip_test_secrets(self): return bool(self.data["security"].get("test_env_must_strip_provider_secrets", True))

    @property
    def backoff_s(self): return list(self.data["retry"]["infrastructure_backoff_s"])

    @property
    def invalid_schema_retries(self): return int(self.data["retry"]["invalid_schema_retries"])

    @property
    def max_fix_cycles(self): return int(self.data["retry"]["max_fix_cycles"])

    @property
    def retryable_exit_codes(self): return set(self.data["retryable_exit_codes"] or [])

    @property
    def human_gate_dir(self): return self.root / self.data["human_gates"]["record_dir"]

    @property
    def acceptance_dir(self): return self.root / self.data["acceptance"]["record_dir"]

    @property
    def registry_path(self): return self.root / self.data["test_registry"]

    @property
    def gate_policy(self): return dict(self.data["gate_policy"])

    def agent(self, name):
        try:
            return dict(self.data["agents"][name])
        except KeyError as e:
            raise ConfigError(f"config.agents.{name} missing") from e
