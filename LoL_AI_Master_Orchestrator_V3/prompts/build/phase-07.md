# BUILD PHASE 07 — Safe Live Upload

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 06 gate PASS and receiver reachable over Tailscale.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Phase 06 receiver API, agent spool from Phase 02

## Architecture
- Client uploader in the agent: persistent SQLite queue (state machine QUEUED→UPLOADING→FINALIZED), 8 MiB chunks, resume via offset query, end-to-end sha256
- Adaptive throttling: measure chunk RTT + OBS dropped-frames signal; priority gameplay > livestream > upload; hard cap configurable (default 60 % of measured uplink)
- Tailscale preflight before any transfer (docs/TAILSCALE_NETWORK.md checklist); tunnel down ⇒ state PAUSED_NETWORK, bounded backoff, NO public fallback ever
- Catch-up after outage rate-limited (no reconnect spike)

## Concrete files
- src/agent/uploader.py, tests/harness/{tailscale_preflight,tailscale_disconnect_resume,no_public_fallback}.py

## Failure modes
- disconnect at 10/50/90 % of a chunk, receiver restart mid-session, queue DB corruption (journal recovery), same segment re-queued

## Tests / metrics
- tailscale_disconnect_resume → resume_duplicate_objects == 0, corrupted_uploads == 0, catchup_after_1h_outage_min ≤ 90
- tailscale_no_public_fallback, tailscale_preflight, tailscale_tenant_isolation
- gate: stream_dropped_frames_pct_delta ≤ 0.5 vs no-uploader baseline (measured during a REAL stream window)

## Real vs mock
- Disconnect/resume over real Tailscale (stop service mid-chunk); baseline comparison on the real streamer PC.

## Human review criteria
- Streamer confirms no perceptible stream impact; 1 GB test per runbook passes.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 07 gate.
