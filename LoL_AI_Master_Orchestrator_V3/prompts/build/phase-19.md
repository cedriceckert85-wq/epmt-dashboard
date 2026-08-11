# BUILD PHASE 19 — Storage Lifecycle

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 16 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- 4 TB HDD budget on central PC

## Architecture
- Retention policy engine: raw segments 14 days (config), reconstructed VODs 30 days, published renders forever, APPROVED-but-unpublished NEVER deleted
- Low/high watermark (free < 200 GB ⇒ aggressive tier; free < 100 GB ⇒ ingest pause + alert), dry-run mode, deletion journal
- Protected-set invariant enforced in code, not convention

## Tests / metrics
- retention_policy_fixture → deleted_protected_objects == 0, free_space_floor_gb ≥ 200; phase_19_tests

## Human review criteria
- Deletion journal auditable; dry-run output matches real run.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 19 gate.
