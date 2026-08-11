# BUILD PHASE 16 — Publishing

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 15 gate PASS. Platform API credentials provisioned by the human.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Approved renders, per-platform metadata templates

## Architecture
- YouTube Data API v3 resumable upload; TikTok Content Posting API; Instagram Graph (Reels) — each behind a platform adapter interface
- Publish ledger: idempotency_key = sha256(render_id+platform); UNIQUE constraint; retry-safe (query-before-create on ambiguous failures)
- Tokens in OS keyring/DPAPI, NEVER in repo/env-files/logs; scheduled publishing windows config
- human_gate: first publish per platform reviewed by the human

## Concrete files
- src/publish/{base,youtube,tiktok,instagram}.py, tests/harness/{publish_idempotency,secret_scan}.py

## Failure modes
- token expiry mid-upload, duplicate webhook/retry, platform-side processing failure, quota exhaustion

## Tests / metrics
- publish_idempotency (sandbox/mocked HTTP) → duplicate_publish_count == 0
- secret_scan_publish → token_leak_findings == 0; phase_16_tests

## Real vs mock
- CI mocks HTTP; ONE real unlisted upload per platform is human-gate evidence.

## Human review criteria
- Ledger prevents double-post under forced retries; tokens invisible in logs.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 16 gate.
