# Phase 00 Go/No-Go

Do NOT start Phase 01 unless:
- Claude doctor PASS
- Codex doctor PASS
- 21 routing fixtures PASS
- agent cannot set PASS
- reviewer cannot write
- tests have no AI provider secrets
- tested/reviewed/approved/merged SHA invariant proven
- timeout kills process tree
- crash recovery never skips gate
- invalid JSON never passes
- human gate never auto-approved
- immutable path edits blocked
- secret findings block
- dirty main blocks
- fix-loop escalation works
- 8h fake orchestrator soak PASS
- cross-vendor review PASS
- human Phase-00 approval for exact commit

Additional V2.2 blockers:
- reviewer findings cannot self-accept
- human approval bound to exact SHA
- reports/human-gates immutable to agents
- lifecycle transition enforcement proven
- clean-main enforcement proven
- phase 00 bootstrap path proven without deadlock
- Windows process tree kill proven
- canonical state has no duplicate status source
- generated markdown projections immutable to agents

Additional V3 blockers:
- test_registry.yaml covers every symbolic phase test (coverage test green)
- gate engine self-validates acceptance records (phase+id+SHA), stale acceptance rejected
- lifecycle validation and completion gate are separate functions; completion gate never used for early transitions
- path policy (immutable-over-allowed, traversal-safe) unit-proven and wired into post-run diff enforcement
