# BUILD PHASE 12 — EDL/Renderer

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 11 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Top highlight candidates, style_profile.json, session media, claude CLI (claude -p, Max subscription — batch top candidates ONLY)

## Architecture
- EDL generation: claude -p with strict JSON schema (schemas/edl.schema.json): cuts[], captions[], zooms[], hook_text; output validated + clamped to media bounds; invalid ⇒ one retry then rule-based fallback EDL (never blocks pipeline)
- Renderer: single ffmpeg filtergraph per clip; NVENC h264 yuv420p CBR 12 Mbit landscape + 9:16 vertical crop variant (subject-follow via fixed center + optional face/champ tracking later); loudnorm two-pass to −14 LUFS
- GPU scheduling: renderer and ASR never run concurrently (simple lock)

## Concrete files
- src/pipeline/edl.py, src/pipeline/render.py, schemas/edl.schema.json, tests/harness/render_eval.py, tests/fixtures/edl/

## Failure modes
- claude CLI quota exhausted (fallback EDL path), NVENC session limit, corrupt filtergraph, loudness overshoot

## Tests / metrics
- render_fixture_suite → render_fail_count == 0, av_sync_drift_ms_max ≤ 40, loudness −15…−13 LUFS, encode_speed_x_min ≥ 1.5 (2080)
- phase_12_tests (EDL validation/clamping unit tests, incl. malicious EDL: out-of-bounds, negative, overlapping)

## Real vs mock
- Fixture EDLs for CI; 5 real highlight renders reviewed at the human gate.

## Human review criteria
- Visual/audio quality acceptable for publishing; vertical crop usable.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 12 gate.
