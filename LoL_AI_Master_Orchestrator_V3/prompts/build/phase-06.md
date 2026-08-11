# BUILD PHASE 06 — Receiver/Security

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 05 gate PASS. Tailscale installed on both machines (runbooks/TAILSCALE_ONBOARDING.md).
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- docs/TAILSCALE_NETWORK.md, runbooks/TAILSCALE_FIREWALL.md, schemas/segment_manifest

## Architecture
- HTTP receiver bound to the Tailscale interface IP ONLY (bind check at startup, refuse 0.0.0.0)
- Device enrollment: one-time enrollment code → per-device token (random 256 bit, hashed at rest); tenant_id derived SERVER-SIDE from token, never from path/payload
- Chunked upload: PUT /v1/segments/{session}/{idx} with Content-Range; offset query endpoint for resume; finalize requires client sha256 == server sha256
- Idempotency: UNIQUE(tenant, session, idx) + UNIQUE(tenant, sha256); duplicate finalize returns the existing object (200, no new row)
- Rate limit per device; structured audit log per request

## Concrete files
- src/receiver/app.py, src/receiver/auth.py, src/receiver/storage.py, tests/harness/{tailscale_binding_check,auth_matrix,tenant_matrix}.py

## Failure modes
- token replay, path traversal in session/idx, second device same tenant, tailnet member WITHOUT app token, receiver restart mid-upload

## Tests / metrics
- receiver_tailscale_binding, app_auth_over_tailscale → auth_bypass_count == 0
- cross_tenant_tailscale_device_denied → cross_tenant_denied_pct == 100, duplicate_logical_objects == 0
- phase_06_tests + adversarial security unit tests (traversal, oversize, malformed range)

## Real vs mock
- Auth/tenant matrix runs over REAL Tailscale between the two machines; CI subset via loopback.

## Human review criteria
- Firewall runbook verified on the real box; Tailscale membership alone grants nothing.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 06 gate.
