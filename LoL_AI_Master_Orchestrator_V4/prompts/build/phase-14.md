# BUILD PHASE 14 — Dashboard

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 13 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- pipeline.db, rendered previews

## Architecture
- FastAPI + minimal web UI, bound to localhost + Tailscale IP only, same auth token scheme as receiver
- Review queue: play preview, approve/reject, trim t0/t1 (re-render job), edit title/hook, keyboard shortcuts (j/k/space/a/r)
- Approval writes state=APPROVED; ONLY approved renders reach Phase 16
- **Humor feedback loop (V4 — this is how the system learns YOUR humor):**
  per clip one-tap ratings (funny 👍/👎) + quick tags (punchline-cut-off,
  too-late-start, not-funny, more-like-this) → clip_feedback table
  (pipeline.db, tenant-scoped). An exporter distills humor_profile.json:
  few-shot examples of approved-funny moments (transcript snippet + why it
  worked) and rejected ones (tag as reason). The phase-10 editorial layer
  loads humor_profile.json as few-shot context when present — ratings from
  each session sharpen the next session's cut. Schema-validated, size-capped
  (top 20 positive / 10 negative, most recent first).

## Concrete files
- src/dashboard/app.py, src/dashboard/static/, tests/phase14/contract/

## Tests / metrics
- dashboard_api_contract → api_contract_failures == 0; phase_14_tests

## Human review criteria
- Reviewing 10 clips takes < 5 min; no accidental publish path without approval.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 14 gate.
