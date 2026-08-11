# BUILD PHASE 08 — 8h Foundation

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phases 02–07 gates PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Full agent+receiver chain, synthetic load generator + one real ~8 h stream

## Architecture
- Soak harness (tests/soak/run_8h_soak.py becomes real): drives synthetic OBS-like segment production + riot fixture replay for 8 h; samples RSS/threads/fds/handles/queue depth/disk every 60 s to metrics JSON
- Log rotation, spool cleanup, worktree/temp hygiene verified over time
- Long-run sync check: re-fit at hour 8 within Phase-04 bounds

## Tests / metrics
- soak_8h_pipeline → rss_growth_mb_per_h_agent ≤ 10, receiver ≤ 20, fd_leak_count == 0, segments_lost == 0, sync_error_p95_ms_at_8h ≤ 100
- phase_08_tests: harness unit tests

## Real vs mock
- 8 h synthetic soak mandatory; the REAL 8 h stream is human-gate evidence (metrics attached).

## Human review criteria
- Time-series plots reviewed; no unexplained step in RSS/fds; disk math sustainable on 4 TB.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 08 gate.
