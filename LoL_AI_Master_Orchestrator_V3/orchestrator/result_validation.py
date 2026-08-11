"""Structured agent-result validation.

Two layers, both mandatory:
1. JSON-Schema validation against schemas/agent_result.schema.json.
2. Binding validation: run_id/phase_id/role in the report must match the
   AgentRequest that produced it. A report for another run (spoofed or
   replayed) can never be attributed to this run.
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def load_schema(schema_path):
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def extract_structured(stdout_text):
    """Best-effort extraction of the structured JSON object from agent
    stdout. Returns dict or None (fail closed - never guesses)."""
    if not stdout_text:
        return None
    text = stdout_text.strip()
    # 1: whole output is the object
    obj = _try_json(text)
    # 2: CLI envelope {"type":"result","result":"<text>"} (claude -p --output-format json)
    if isinstance(obj, dict) and "result" in obj and isinstance(obj.get("result"), str):
        inner = _try_json(_strip_fences(obj["result"].strip()))
        if isinstance(inner, dict):
            return inner
    if isinstance(obj, dict):
        return obj
    # 3: last non-empty line is the object (fake agent, jsonl-style CLIs)
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        obj = _try_json(_strip_fences(line))
        if isinstance(obj, dict):
            return obj
        break
    # 4: fenced block anywhere
    obj = _try_json(_strip_fences(text))
    return obj if isinstance(obj, dict) else None


def _strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _try_json(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def validate_agent_result(structured, *, schema, request):
    """Returns a list of error strings; empty list == valid AND bound to
    this exact request."""
    if structured is None:
        return ["no structured JSON result found in agent output"]
    validator = Draft202012Validator(schema)
    errors = [f"schema: {e.message}" for e in validator.iter_errors(structured)]
    if errors:
        return errors
    if structured.get("run_id") != request.run_id:
        errors.append(f"binding: run_id {structured.get('run_id')!r} != request {request.run_id!r}")
    if str(structured.get("phase_id")) != str(request.phase_id):
        errors.append(f"binding: phase_id {structured.get('phase_id')!r} != request {request.phase_id!r}")
    if structured.get("role") != str(request.role):
        errors.append(f"binding: role {structured.get('role')!r} != request {request.role!s}")
    seen = set()
    for f in structured.get("findings", []):
        fid = f.get("id")
        if fid in seen:
            errors.append(f"duplicate finding id: {fid}")
        seen.add(fid)
    return errors
