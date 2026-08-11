# BUILD PHASE 17 — Analytics

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 16 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Architecture
- Daily pull: YouTube Analytics, TikTok/IG basic metrics → analytics tables (idempotent upsert by (platform, remote_id, date))
- Simple weekly report (views, retention, best hook) as markdown to dashboard

## Tests / metrics
- analytics_ingest_idempotency → ingest_duplicate_rows == 0; phase_17_tests
## Concrete files
- src/publish/analytics.py, tests/harness/analytics_eval.py, migrations for analytics tables

## Failure modes
- API quota exhaustion (resume next day, no gaps), remote_id deleted on platform, timezone-shifted daily buckets, partial-day double pull

## Real vs mock
- CI mocks HTTP fixtures; one real pull against the unlisted Phase-16 uploads as evidence.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 17 gate.
