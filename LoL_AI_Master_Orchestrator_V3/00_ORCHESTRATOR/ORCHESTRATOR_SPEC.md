# Phase 00 — Orchestrator Specification

## Muss implementiert werden
- Python CLI
- Claude adapter
- Codex adapter
- Process isolation
- Timeouts + cancellation + child-process kill
- stdout/stderr capture
- structured result validation
- prompt routing
- builder/tester/reviewer/fixer roles
- deterministic gate engine
- canonical state store
- generated markdown projections
- git worktree/checkpoint/merge control
- single-writer lock
- allowed-path enforcement
- secret scan
- human gates
- retry policy
- crash recovery
- safe rollback
- CLI version doctor
- dry-run/fake-agent mode
- audit log

## Nicht akzeptabel
- LLM entscheidet PASS
- gleicher Agent gilt als unabhängiger Reviewer
- Retry-Endlosschleifen
- Agent darf Gate Config ändern
- Markdown ist einzige State-Quelle
- Tests laufen mit Provider-Secrets im Environment


## Network capability checks
The orchestrator/doctor must support Tailscale preflight for phases that require real streamer↔receiver transfer:
- executable/service availability
- tunnel reachability
- configured receiver identity/address
- no silent public fallback
- explicit UNVERIFIED/BLOCKED if real network evidence is unavailable
