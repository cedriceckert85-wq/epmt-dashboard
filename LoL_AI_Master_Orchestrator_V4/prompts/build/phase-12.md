# BUILD PHASE 12 — EDL/Renderer

## ⚠ VENDORED FIELD-TESTED CORE — adopt, do not re-derive

`vendor/clip_lab_core/` ships the PROVEN implementation of this phase's
architecture (LoL Clip Lab V2: 222 passing tests, adversarially audited, run
against real ffmpeg and a real `claude -p` loop). Read `docs/VENDORED_CORE.md`
FIRST. Start your implementation from that package and extend it; keep its
tests green against your adaptation. Re-implementing its mechanics from
scratch (whole-script chunked session pass, channel memory, multi-style
references with format-vs-cut classification, channel routing + chapters,
dual-brain blend, punchline-aware EDL, all sanitization/hardening) is a
review blocker — those mechanics encode hundreds of verified fixes.

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 11 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Top highlight candidates incl. editorial data (phase 10: category, punchline_ts,
  callback_refs/callback_insert, zoom/sfx suggestions, session_context.json),
  style_profile.json, session media, claude CLI (claude -p, Max subscription — batch top candidates ONLY)

## Architecture
- EDL generation: claude -p with strict JSON schema (schemas/edl.schema.json): cuts[], captions[], zooms[], sfx[], callback_inserts[], hook_text; the prompt INCLUDES the editorial context (why the moment is funny/hype, punchline_ts, callback text+timestamps) so captions/zooms/sfx land ON the punchline, not just on kills; output validated + clamped to media bounds; invalid ⇒ one retry then rule-based fallback EDL (never blocks pipeline)
- SFX/music: local library folders (assets/sfx/, assets/music/ — user-provided,
  licensed; ship empty with README); sfx[] entries reference library ids only;
  missing id ⇒ skip entry, log; audio ducking under SFX; never download media
- callback_inserts: render as brief picture-in-picture or hard-cut insert of the
  referenced earlier window (max 5 s), with caption from editorial context
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
