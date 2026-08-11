"""High-finding acceptance records.

Records live in an orchestrator-owned, agent-immutable directory
(config: acceptance.record_dir, default reports/acceptance/) and follow
schemas/finding_acceptance.schema.json. The gate engine validates every
record itself - it never trusts a pre-built id set.
"""
import json
from pathlib import Path

REQUIRED = ("phase_id","finding_id","commit_sha","decision","reason","approver","timestamp_utc")


def load_records(record_dir):
    """Load all *.json acceptance records. Unreadable files are returned
    as error markers so the gate can surface them (fail closed)."""
    records=[]
    d=Path(record_dir)
    if not d.exists() or d.is_symlink():
        return records
    for p in sorted(d.glob("*.json")):
        # never follow a symlinked record: a forged acceptance planted as a
        # symlink to an out-of-tree file is rejected outright
        if p.is_symlink() or not p.is_file():
            records.append({"__load_error__": f"{p.name}: refused (symlink/non-regular file)"})
            continue
        try:
            records.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            records.append({"__load_error__": f"{p.name}: {e}"})
    return records


def validate_record(rec, *, phase_id, candidate_commit):
    """Returns (finding_id | None, error | None).
    finding_id is returned ONLY for a fully valid ACCEPT record bound to
    this phase and this exact candidate SHA."""
    if "__load_error__" in rec:
        return None, f"unreadable acceptance record: {rec['__load_error__']}"
    missing=[k for k in REQUIRED if not str(rec.get(k) or "").strip()]
    if missing:
        return None, f"acceptance record incomplete (missing {','.join(missing)})"
    if rec["decision"] not in ("ACCEPT","REJECT"):
        return None, f"acceptance record invalid decision: {rec['decision']}"
    if rec["decision"] != "ACCEPT":
        return None, None            # explicit REJECT: valid record, accepts nothing
    if str(rec["phase_id"]) != str(phase_id):
        return None, None            # record for another phase: ignore here
    if rec["commit_sha"] != candidate_commit:
        # SHA-scoped: a stale acceptance simply accepts nothing on the new
        # candidate. It must NOT be surfaced as a gate-blocking error —
        # otherwise an acceptance an operator wrote for an earlier candidate
        # would permanently block the phase even after a clean fresh rebuild
        # that has none of the accepted findings. The SHA scoping already
        # guarantees it can never leak onto the wrong candidate.
        return None, None
    return str(rec["finding_id"]), None


def accepted_ids(records, *, phase_id, candidate_commit):
    """(set_of_accepted_ids, list_of_reasons_for_invalid_records)"""
    ids=set(); reasons=[]
    for rec in records or []:
        fid, err = validate_record(rec, phase_id=phase_id, candidate_commit=candidate_commit)
        if fid: ids.add(fid)
        if err: reasons.append(err)
    return ids, reasons
