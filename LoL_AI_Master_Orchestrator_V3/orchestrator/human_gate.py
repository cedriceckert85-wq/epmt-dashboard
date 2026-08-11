"""Human-gate approval records (reports/human-gates/).

A record binds approver + decision to ONE exact candidate SHA of ONE
phase. The gate engine re-validates the record itself; a record for a
different SHA can never release a candidate ("human_approval_must_bind_
exact_sha").
"""
import json, time
from pathlib import Path

from .journal import utc_now

VALID_DECISIONS = ("APPROVE", "REJECT")


class HumanGateError(Exception):
    pass


def record_decision(record_dir, *, phase_id, commit_sha, approver, decision, reason=""):
    if decision not in VALID_DECISIONS:
        raise HumanGateError(f"invalid decision: {decision!r}")
    for name, val in (("phase_id", phase_id), ("commit_sha", commit_sha), ("approver", approver)):
        if not str(val or "").strip():
            raise HumanGateError(f"missing {name}")
    d = Path(record_dir)
    d.mkdir(parents=True, exist_ok=True)
    approval_id = f"hg-{phase_id}-{int(time.time() * 1000)}"
    rec = {
        "approval_id": approval_id,
        "phase_id": str(phase_id),
        "commit_sha": str(commit_sha),
        "approver": str(approver),
        "decision": decision,
        "reason": str(reason or ""),
        "timestamp_utc": utc_now(),
    }
    path = d / f"{approval_id}.json"
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec, path


def latest_decision(record_dir, *, phase_id, commit_sha):
    """Newest valid record for exactly this phase+SHA, or None. Records
    for other SHAs/phases are ignored here — the gate engine separately
    verifies SHA binding again."""
    d = Path(record_dir)
    if not d.exists():
        return None
    best = None
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("decision") not in VALID_DECISIONS:
            continue
        if str(rec.get("phase_id")) != str(phase_id):
            continue
        if rec.get("commit_sha") != commit_sha:
            continue
        if best is None or str(rec.get("approval_id", "")) > str(best.get("approval_id", "")):
            best = rec
    return best
