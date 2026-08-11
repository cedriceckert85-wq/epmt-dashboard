"""Compose the full prompt file an agent receives for one run.

Structure: role preamble (rules, result contract) + current task JSON +
phase prompt (build/review lenses/fix) + run-specific evidence.
"""
import json
from pathlib import Path

from .resultio import RESULT_REL_PATH

PREAMBLE = """# ORCHESTRATOR RUN — {role_upper} — Phase {phase_id} ({phase_name})

You are the **{role}** in a deterministic multi-agent build. A Python
orchestrator — not you — owns lifecycle, gates, git and tests.

## Hard rules
- Work ONLY inside the current working directory (the project root).
- You may write ONLY under these paths: {allowed_paths}
- You must NEVER modify (immutable, enforced by diff inspection afterwards):
  {immutable_paths}
- Do NOT run git commit/merge/rebase/tag/push. The orchestrator commits.
- Do NOT create or modify approval/acceptance records or gate/test configs.
- You cannot approve or pass a phase. "PASS" comes only from real test
  exit codes and the gate engine.
- If something cannot be verified, say UNVERIFIED in your result. Never guess.
- Never put anything that looks like a real API key/token/private key into
  code, fixtures or docs — a deterministic secret scan blocks the phase.
  Use obviously fake short placeholders instead.

## Required result file (MANDATORY)
Before you finish, write the file `{result_path}` (schema:
schemas/agent_result.schema.json) with EXACTLY this shape:

```json
{{
  "run_id": "{run_id}",
  "phase_id": "{phase_id}",
  "role": "{role}",
  "status": "completed | blocked | failed | unverified",
  "summary": "what you did / found",
  "findings": [
    {{"id": "stable-unique-id", "severity": "blocker|high|medium|low",
      "title": "...", "evidence": "...", "file": "...", "line": null}}
  ],
  "tests": [
    {{"name": "symbolic-test-name", "status": "pass|fail|unverified", "evidence": "..."}}
  ]
}}
```

A missing or schema-invalid result file fails this run.

## Current task (generated from canonical state)
```json
{task_json}
```
"""

ROLE_NOTES = {
    "builder": """## Role notes — BUILDER
Implement the phase specification below. Write code + tests under your
allowed paths. Run the phase's registry test commands locally while you
work (they will be re-run by the orchestrator with a clean environment —
only those runs count). Do not touch other phases.
""",
    "reviewer": """## Role notes — REVIEWER (read-only)
You review the CURRENT CHECKED-OUT candidate commit of another vendor's
work. You may READ everything but WRITE nothing except your result file
under reports/. Any other write is reverted and counted as a violation.
Verify claims against the actual code/tests — do not trust reports.
Report findings with stable unique ids, severity (blocker/high/medium/low),
concrete evidence, reproduction, expected vs actual. Do NOT fix anything.
""",
    "fixer": """## Role notes — FIXER
Fix ONLY the verified findings / failing tests listed below. For each:
reproduce first, then smallest fix, then regression test. Never weaken
tests, thresholds or gates to get green. Stay inside allowed paths.
""",
}


def build_prompt(*, root, run_id, phase, role, task, immutable_paths,
                 allowed_paths, phase_prompt_files, extra_sections=()):
    parts = [PREAMBLE.format(
        role=role, role_upper=role.upper(),
        phase_id=phase["id"], phase_name=phase.get("name", ""),
        allowed_paths=", ".join(allowed_paths) or "(none)",
        immutable_paths=", ".join(immutable_paths),
        result_path=RESULT_REL_PATH,
        run_id=run_id,
        task_json=json.dumps(task, indent=2),
    )]
    parts.append(ROLE_NOTES.get(role, ""))
    for rel in phase_prompt_files:
        p = Path(root) / rel
        if p.exists():
            parts.append(f"\n---\n\n# PHASE PROMPT: {rel}\n\n" + p.read_text(encoding="utf-8"))
        else:
            parts.append(f"\n---\n\n# PHASE PROMPT MISSING: {rel}\n(File not found — "
                         f"report this as a blocker finding, do not improvise.)")
    for title, body in extra_sections:
        parts.append(f"\n---\n\n# {title}\n\n{body}")
    return "\n".join(parts)


def write_prompt_file(artifact_dir, name, text):
    p = Path(artifact_dir) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p
