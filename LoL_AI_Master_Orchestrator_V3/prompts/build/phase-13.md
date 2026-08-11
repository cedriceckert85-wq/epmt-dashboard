# BUILD PHASE 13 — Automatic Cut Rules

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 12 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Highlights + style profile

## Architecture
- Deterministic pre/post-roll per event type (kill 4 s/3 s, steal 8 s/4 s, reaction 2 s/4 s — config), clip length clamp 12–45 s, overlap merge, per-video chaptering for compilations
- Pure functions, no LLM

## Tests / metrics
- cutrule_determinism → cut_determinism == 1, clip_len_violations == 0; phase_13_tests

## Human review criteria
- 10 sampled clips start/end feel right (no cut mid-fight-start).
## Concrete files
- src/pipeline/cutrules.py, tests/harness/cutrules_eval.py, config/cutrules.toml

## Failure modes
- overlapping highlight windows collapsing into one giant clip, event at segment boundary, pre-roll reaching before session start, style profile missing (fall back to defaults, flag in report)

## Real vs mock
- Fully deterministic/unit-testable; golden fixtures from 2 real sessions.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 13 gate.
