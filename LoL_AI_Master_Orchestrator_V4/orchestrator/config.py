"""Load and validate ORCHESTRATOR_CONFIG.yaml. Fail closed on anything odd."""
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


REQUIRED_TOP_KEYS = ("version", "project", "agents", "retry", "security", "git",
                     "human_gates", "acceptance", "test_registry", "gate_policy")


class Config:
    def __init__(self, root, data):
        self.root = Path(root)
        self.data = data

    # -- convenience accessors -------------------------------------------
    @property
    def project(self):
        return self.data["project"]

    @property
    def immutable_paths(self):
        return list(self.data["security"]["immutable_paths"])

    @property
    def gate_mode(self):
        return self.data.get("execution", {}).get("gate_mode", "auto")

    @property
    def max_fix_cycles(self):
        return int(self.data["retry"].get("max_fix_cycles", 2))

    @property
    def invalid_schema_retries(self):
        return int(self.data["retry"].get("invalid_schema_retries", 1))

    @property
    def infra_backoff(self):
        return list(self.data["retry"].get("infrastructure_backoff_s", [5, 20]))

    @property
    def secret_env_vars(self):
        return list(self.data["security"].get("strip_env_vars", []))

    @property
    def artifact_root(self):
        return self.root / self.project.get("artifact_root", ".orchestrator/artifacts")

    @property
    def state_file(self):
        return self.root / self.project["canonical_state"]

    @property
    def journal_file(self):
        return self.root / self.project["journal"]

    @property
    def lock_file(self):
        return self.root / self.project["lock_file"]

    def agent_cfg(self, provider):
        try:
            return self.data["agents"][provider]
        except KeyError:
            raise ConfigError(f"unknown agent provider: {provider}")


def load_config(root, path=None):
    root = Path(root)
    cfg_path = Path(path) if path else root / "ORCHESTRATOR_CONFIG.yaml"
    if not cfg_path.exists():
        raise ConfigError(f"config missing: {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("config is not a mapping")
    missing = [k for k in REQUIRED_TOP_KEYS if k not in data]
    if missing:
        raise ConfigError(f"config missing keys: {', '.join(missing)}")
    for prov in ("claude", "codex"):
        if prov not in data["agents"]:
            raise ConfigError(f"config agents.{prov} missing")
    return Config(root, data)


def load_phase(root, phase_id):
    p = Path(root) / "phases" / f"phase-{phase_id}.yaml"
    if not p.exists():
        raise ConfigError(f"phase config missing: {p}")
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    if str(d.get("id")).zfill(2) != str(phase_id).zfill(2):
        raise ConfigError(f"phase file {p} id mismatch: {d.get('id')!r}")
    d["id"] = str(d["id"]).zfill(2)
    for key in ("name", "builder", "reviewer", "required_tests", "allowed_write_paths"):
        if key not in d:
            raise ConfigError(f"phase {phase_id}: missing key {key}")
    if d["builder"] == d["reviewer"] and d.get("cross_vendor_review", True):
        raise ConfigError(f"phase {phase_id}: builder and reviewer must differ (cross-vendor)")
    return d


def list_phase_ids(root):
    ids = []
    for p in sorted((Path(root) / "phases").glob("phase-*.yaml")):
        ids.append(p.stem.split("-", 1)[1].zfill(2))
    return sorted(set(ids))
