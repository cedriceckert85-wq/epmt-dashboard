# BUILD PHASE 18 — Multi-Streamer (OPTIONAL — disabled by default)

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Explicit user decision to enable. Phase 16 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Architecture
- Tenant provisioning CLI (enrollment code, quotas: max concurrent uploads, storage GB), per-tenant dashboards/queues; all isolation already enforced since Phase 06 — this phase adds provisioning + quotas only

## Tests / metrics
- cross_tenant_denied_pct == 100 re-run with 2 real tenants; phase_18_tests

## Human review criteria
- Second streamer onboarded via runbook without code changes.
## Concrete files
- src/tools/tenant_admin.py (enroll/revoke/quota), per-tenant config in DB, dashboard tenant switcher

## Failure modes
- quota exhaustion of tenant A starving tenant B (fair scheduling), revoked device still holding a valid-looking token (revocation list checked per request), storage accounting drift

## Real vs mock
- Both-real-tenant matrix over Tailscale (second streamer PC or a second enrolled VM); runbooks/TAILSCALE_ONBOARDING.md executed verbatim.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 18 gate.
