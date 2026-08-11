# BUILD PHASE 04 — Sync Engine

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phases 02+03 gates PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Riot samples (game_time_ms ↔ sampled_mono_ns), segment boundaries (mono_ns ↔ OBS media time), OBS segment PTS

## Architecture
- Primary timebase: agent monotonic clock
- Mapping A: riot game_time → agent mono via robust linear fit (Theil–Sen or RANSAC), outlier rejection, piecewise segments at discontinuities (pause, reconnect, clock jump)
- Mapping B: agent mono → media timeline via segment start offsets (segment idx * duration + intra-PTS)
- Output per session: sync_map JSON {pieces:[{t0,t1,slope,offset}], rmse_ms, confidence}; mapped time must be monotonic
- Explicit handling: wall-clock is NEVER used for mapping, only for display

## Concrete files
- src/core/sync.py, tests/harness/sync_eval.py, tests/fixtures/sync/ (generator script included)

## Failure modes / fixtures (harness must include exactly these)
- 100 ppm drift, 500 ppm drift, 20 % missing samples, 2 s riot disconnect, OBS segment switch mid-event, wall clock +1 h jump, game pause 60 s

## Tests / metrics (gate)
- sync_drift_fixtures → sync_error_p95_ms ≤ 100, p99 ≤ 250, max ≤ 500, mapped_time_nonmonotonic_count == 0
- phase_04_tests: unit tests for fit/piecewise/confidence

## Real vs mock
- Fixtures synthetic; one real session end-to-end mapped and spot-checked (kill visible at mapped timestamp ± 500 ms) for the human gate.

## Human review criteria
- Spot-check 5 events in real footage; confidence/rmse reported honestly.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 04 gate.
