# BUILD PHASE 05 — Segmentation/Reconstruction

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 04 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Uploaded validated segments per session (post Phase 06/07 locally simulated for now: use local segment store)

## Architecture
- Server-side reconstructor: order by idx, verify continuity (expected start = prev end ± 50 ms), detect/gap-mark missing segments, build concat plan (ffmpeg concat demuxer, stream copy, NO re-encode)
- A/V drift check across joins (ffprobe first/last PTS per track)
- Output: session timeline manifest consumed by renderer

## Concrete files
- src/receiver/reconstruct.py, tests/harness/reconstruct_eval.py, fixtures with seeded gaps/overlaps

## Failure modes
- missing middle segment, duplicate idx with different sha, overlapping PTS, audio track count mismatch, last-segment short

## Tests / metrics
- reconstruction_fixtures → pts_overlap_count == 0, undetected_gap_count == 0, av_desync_ms_max ≤ 50
- phase_05_tests

## Real vs mock
- Fixture-driven; real 8 h material exercised in Phase 08.

## Human review criteria
- Gap report human-readable; stream-copy verified (no quality loss).

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 05 gate.
