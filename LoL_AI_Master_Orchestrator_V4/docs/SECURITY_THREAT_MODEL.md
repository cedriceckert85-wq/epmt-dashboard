# Security Threat Model

Threats:
- prompt injection in repo content
- provider secret exposure
- cross-tenant access
- path traversal/symlink/junction escape
- replay/idempotency failure
- reviewer write access
- gate/state spoofing
- git candidate mismatch
- malicious tests/hooks
- stale human approvals

Controls:
- deterministic state/gates
- immutable control-plane paths
- scrubbed test environment
- separate provider runners
- read-only reviewer worktree
- server-derived tenant identity
- unique constraints/idempotency
- exact-SHA human approvals
