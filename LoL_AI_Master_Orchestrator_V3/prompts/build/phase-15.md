# BUILD PHASE 15 — Full Game Export

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 14 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Reconstructed session timeline, riot events for chapters

## Architecture
- Full-VOD assembly (stream copy), YouTube chapter file from events (game start, kills, objectives), optional 2× dead-time speedup variant (re-encode NVENC)

## Tests / metrics
- fullgame_export_fixture → duration_delta_ms_max ≤ 500, chapter_offset_error_ms_max ≤ 1000; phase_15_tests

## Human review criteria
- Chapters land on the right moments in one real VOD.
## Concrete files
- src/pipeline/fullgame.py, tests/harness/fullgame_eval.py

## Failure modes
- gap in reconstruction (chapter times shift — must re-anchor per piece), >2 h VOD memory pressure during speedup re-encode, chapter text collisions

## Real vs mock
- Fixture sessions for CI; one real VOD export with visual chapter spot-check for the human gate (Phase 16 uploads it unlisted).

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 15 gate.
