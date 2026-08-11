# BUILD PHASE 03 — Riot Live Data

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 01 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Riot Live Client Data API on the GAME PC: https://127.0.0.1:2999/liveclientdata/ (self-signed; pin riotgames.pem, no verify=False)

## Architecture
- Poller in the streamer agent: /allgamedata every 1000 ms, /eventdata delta by EventID
- Every sample stored raw (JSONL per session) with wall_utc + agent monotonic_ns
- Session detection: API reachable + gameTime increasing = active; gameTime reset or 30 s unreachable = session end; new session id on restart
- Dedupe: UNIQUE(session_id, event_id); reconnect must not replay events as new
- Pause handling: gameTime frozen (pause) vs API gone (loading/disconnect) are distinct states

## Concrete files
- src/agent/riot_poller.py, src/core/riot_models.py, fixtures: tests/fixtures/riot/*.jsonl

## Failure modes
- practice tool/custom games, spectator mode (no activePlayer), API flapping, duplicate EventIDs across reconnect, clock jump between samples

## Tests
- riot_event_dedupe: fixture replay with duplicated/reordered events → event_duplicate_count == 0
- riot_reconnect_fixture: 2 s and 30 s outages → correct session semantics, sample_gap_p99_ms ≤ 2500
- phase_03_tests: unit tests, cert pinning test (self-signed accepted ONLY via pinned CA)

## Real vs mock
- Fixtures for CI; one REAL League match capture is mandatory human-gate evidence.

## Human review criteria
- Raw JSONL complete for the real match; no TLS verification bypass anywhere.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 03 gate.
