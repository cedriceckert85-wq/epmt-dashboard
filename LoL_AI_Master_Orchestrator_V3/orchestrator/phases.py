"""Phase config loader (phases/phase-XX.yaml). Fail closed on missing
files/fields; agents can never inject a phase config (immutable path)."""
import yaml
from pathlib import Path

REQUIRED = ("id", "name", "builder", "reviewer", "human_gate", "required_tests",
            "allowed_write_paths", "gate")


class PhaseError(Exception):
    pass


def load_phase(root, phase_id):
    p = Path(root) / "phases" / f"phase-{phase_id}.yaml"
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PhaseError(f"phase config missing: {p}") from e
    except yaml.YAMLError as e:
        raise PhaseError(f"phase config invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise PhaseError(f"phase config not a mapping: {p}")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise PhaseError(f"phase {phase_id} config incomplete: missing " + ", ".join(missing))
    if str(data["id"]) != str(phase_id):
        raise PhaseError(f"phase id mismatch: file says {data['id']!r}, expected {phase_id!r}")
    return data


def next_phase_id(root, phase_id):
    """The next phase file in lexicographic order, or None after the last."""
    ids = sorted(p.stem.split("-", 1)[1] for p in (Path(root) / "phases").glob("phase-*.yaml"))
    try:
        i = ids.index(str(phase_id))
    except ValueError:
        return None
    return ids[i + 1] if i + 1 < len(ids) else None
