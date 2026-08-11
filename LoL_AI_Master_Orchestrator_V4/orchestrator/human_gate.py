"""Human-gate records (reports/human-gates/, agent-immutable).

Two modes (execution.gate_mode):
- auto   (one-shot default): the orchestrator writes an AUTO_GATE approval
  record bound to the exact candidate SHA — but ONLY after every
  deterministic criterion (tests, review, secret scan, SHA identity)
  already holds. The record documents that the operator pre-authorized
  autonomous approval by starting the one-shot run.
- strict (V3 behavior): the run pauses; a human runs
  `python -m orchestrator approve --phase NN --commit SHA --approver NAME
  --decision APPROVE` and then restarts the run (it resumes).
"""
from pathlib import Path

from .util import atomic_write_json, new_id, utc_now_iso


def record_path(record_dir, phase_id, commit_sha):
    return Path(record_dir) / f"phase-{phase_id}-{commit_sha[:12]}.json"


def load_approval(record_dir, phase_id, commit_sha):
    p = record_path(record_dir, phase_id, commit_sha)
    # refuse to follow a symlink: a forged approval planted as a symlink to an
    # out-of-tree file must never be honored (defense in depth beside the
    # integrity snapshot that records symlinks as tampering).
    if p.is_symlink() or (p.parent.exists() and p.parent.is_symlink()):
        return None
    if not p.is_file():
        return None
    import json
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if rec.get("phase_id") != phase_id or rec.get("commit_sha") != commit_sha:
        return None
    return rec


def write_approval(record_dir, *, phase_id, commit_sha, approver, decision,
                   mode, evidence=None):
    rec = {
        "approval_id": new_id("approval"),
        "phase_id": phase_id,
        "commit_sha": commit_sha,
        "approver": approver,
        "decision": decision,
        "mode": mode,
        "timestamp_utc": utc_now_iso(),
        "evidence": evidence or {},
    }
    p = record_path(record_dir, phase_id, commit_sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, rec)
    return rec
