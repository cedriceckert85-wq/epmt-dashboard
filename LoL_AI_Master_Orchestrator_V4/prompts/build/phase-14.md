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

## Concrete files
- src/dashboard/app.py, src/dashboard/static/, tests/phase14/contract/

## Tests / metrics
- dashboard_api_contract → api_contract_failures == 0; phase_14_tests

## Human review criteria
- Reviewing 10 clips takes < 5 min; no accidental publish path without approval.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 14 gate.
