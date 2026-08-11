# BUILD PHASE 01 — Architecture/Data Model

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 00 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- MASTER_ORCHESTRATOR.md, docs/ARCHITECTURE.md, docs/TAILSCALE_NETWORK.md
- Hardware envelope: central PC with RTX 2080, 4 TB HDD; 1 streamer PC (Windows)

## Architecture to implement
- Monorepo layout: src/agent (Windows streamer agent), src/receiver, src/core (shared models/time), src/pipeline (asr/vision/rank/edl/render), src/dashboard, src/publish
- Central store: SQLite in WAL mode (single writer per DB), one DB per concern: ingest.db, pipeline.db, publish.db
- IDs: ULIDs everywhere; every row carries tenant_id
- Dual timestamps on every time-bearing row: wall_utc + monotonic_ns + clock_domain tag (AGENT_MONO, RIOT_GAME, OBS_PTS)

## Concrete files
- src/core/models.py, src/core/timebase.py, src/core/db.py, migrations/0001_init.sql
- schemas/*.schema.json for: segment_manifest, riot_sample, sync_map, highlight, edl, publish_record

## Data model (tables, minimum columns)
- sessions(id, tenant_id, started_wall_utc, agent_boot_id, status)
- segments(id, session_id, idx, t_start_mono_ns, duration_ms, sha256, bytes, state[RECORDED|VALIDATED|UPLOADED|STORED], UNIQUE(session_id, idx), UNIQUE(tenant_id, sha256))
- riot_events(id, session_id, event_id, game_time_ms, sampled_mono_ns, payload_json, UNIQUE(session_id, event_id))
- sync_maps(session_id, model_json, confidence, rmse_ms)
- highlights(id, session_id, t0_ms, t1_ms, score, reason_json, state)
- renders(id, highlight_id, profile, path, state)
- publishes(id, render_id, platform, remote_id, idempotency_key UNIQUE, state)

## Failure modes to design for
- agent restart mid-session (boot_id changes), duplicate segment upload, partial DB writes, schema drift

## Tests (see test_registry.yaml)
- schema_roundtrip: every JSON schema validates golden fixtures and rejects mutated ones
- migration_up_down: apply → downgrade → apply, byte-identical dump
- phase_01_tests: model/DB unit tests

## Real vs mock
- All Phase-01 tests are mock/fixture based; no hardware.

## Human review criteria
- Data model covers every later phase's needs (walk phases 02–20 against it); no tenant-less table; no naive datetime.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 01 gate.
