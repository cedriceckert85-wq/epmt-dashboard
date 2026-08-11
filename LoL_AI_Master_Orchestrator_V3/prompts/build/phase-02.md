# BUILD PHASE 02 — OBS Agent (Windows)

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 01 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- OBS 30+ on streamer PC, recording MKV, audio tracks: T1 full mix, T2 mic only, T3 game only
- OBS automatic file splitting: 300 s segments (use OBS native split; do NOT re-split with ffmpeg)

## Architecture
- Windows tray app/service (Python or Go), single-instance lock file
- Watches OBS output dir; a segment is picked up ONLY after OBS closes it (file stable for >2 s and ffprobe-parsable)
- Per segment: ffprobe validation (duration 295–305 s except last, monotonic PTS, 3 audio tracks), sha256, manifest row (segments table via local agent DB), enqueue for upload
- Records agent monotonic clock + wall clock at segment boundaries for the sync engine
- Config in %APPDATA%/lolcutter/config.toml; structured JSONL logs with rotation

## Concrete files
- src/agent/main.py, src/agent/watcher.py, src/agent/validate.py, src/agent/spool.py, src/agent/clock.py

## Failure modes
- OBS crash mid-segment (last file invalid → quarantine, never upload), disk full (stop OBS-safe: pause pickup + alert, never delete), unicode/emoji filenames, sleep/resume (monotonic jump tagging), agent crash (resume from DB state, no re-hash of validated files)

## Tests
- segment_validation_fixtures: golden set incl. truncated file, missing track, PTS jump — expected verdicts
- agent_crash_recovery: kill agent at defined points, restart, assert no loss/dup (Windows harness)
- phase_02_tests: unit tests for watcher/validate/spool

## Real vs mock
- Fixture MKVs generated with ffmpeg for CI; one REAL OBS session on the streamer PC is mandatory evidence for the human gate.

## Human review criteria
- Live OBS recording untouched in quality; CPU p95 ≤ 5 %, RAM ≤ 300 MB while recording; quarantine works.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 02 gate.
