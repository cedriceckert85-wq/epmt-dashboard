"""Agent result contract: agents write reports/agent_result.json.

Validated here against the (fixed) shape of schemas/agent_result.schema.json
without needing the jsonschema package. Fail closed: anything malformed is
rejected with precise reasons.
"""
import json
from pathlib import Path

RESULT_REL_PATH = "reports/agent_result.json"

VALID_STATUS = {"completed", "blocked", "failed", "unverified"}
VALID_ROLE = {"builder", "reviewer", "fixer", "researcher"}
VALID_SEVERITY = {"blocker", "high", "medium", "low"}
VALID_TEST_STATUS = {"pass", "fail", "unverified"}
REQUIRED_KEYS = ("run_id", "phase_id", "role", "status", "summary", "findings", "tests")


def validate_agent_result(obj, *, expected_phase, expected_role):
    """Return list of problems; empty list == valid."""
    problems = []
    if not isinstance(obj, dict):
        return ["result is not a JSON object"]
    for k in REQUIRED_KEYS:
        if k not in obj:
            problems.append(f"missing key: {k}")
    if problems:
        return problems
    if not isinstance(obj["summary"], str) or not obj["summary"].strip():
        problems.append("summary must be a non-empty string")
    if obj["role"] not in VALID_ROLE:
        problems.append(f"invalid role: {obj['role']!r}")
    elif obj["role"] != expected_role:
        problems.append(f"role mismatch: expected {expected_role}, got {obj['role']}")
    if obj["status"] not in VALID_STATUS:
        problems.append(f"invalid status: {obj['status']!r}")
    if str(obj["phase_id"]).zfill(2) != str(expected_phase).zfill(2):
        problems.append(f"phase mismatch: expected {expected_phase}, got {obj['phase_id']}")
    if not isinstance(obj["findings"], list):
        problems.append("findings must be an array")
    else:
        seen_ids = set()
        for i, f in enumerate(obj["findings"]):
            if not isinstance(f, dict):
                problems.append(f"finding[{i}] not an object")
                continue
            fid = f.get("id")
            if not isinstance(fid, str) or not fid.strip():
                problems.append(f"finding[{i}] missing stable id")
            elif fid in seen_ids:
                problems.append(f"finding id duplicated: {fid}")
            else:
                seen_ids.add(fid)
            if f.get("severity") not in VALID_SEVERITY:
                problems.append(f"finding[{i}] invalid severity: {f.get('severity')!r}")
            if not isinstance(f.get("title"), str) or not f.get("title", "").strip():
                problems.append(f"finding[{i}] missing title")
    if not isinstance(obj["tests"], list):
        problems.append("tests must be an array")
    else:
        for i, t in enumerate(obj["tests"]):
            if not isinstance(t, dict) or not t.get("name") or t.get("status") not in VALID_TEST_STATUS:
                problems.append(f"tests[{i}] invalid (need name + status pass/fail/unverified)")
    return problems


def read_agent_result(workspace, *, expected_phase, expected_role):
    """(result | None, problems). Missing/unparseable file => problems."""
    p = Path(workspace) / RESULT_REL_PATH
    if not p.exists():
        return None, [f"agent did not write {RESULT_REL_PATH}"]
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, [f"{RESULT_REL_PATH} unreadable/invalid JSON: {e}"]
    problems = validate_agent_result(obj, expected_phase=expected_phase, expected_role=expected_role)
    return (obj if not problems else None), problems


def clear_agent_result(workspace):
    p = Path(workspace) / RESULT_REL_PATH
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
