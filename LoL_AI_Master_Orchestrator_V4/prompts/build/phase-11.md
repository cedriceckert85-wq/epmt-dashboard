# BUILD PHASE 11 — Reference Style

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
- Phase 10 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- 10–30 hand-picked reference videos of the EXACT target style (user-provided
  files; consistency beats quantity), sample own footage

## Architecture
- Style profile extractor → style_profile.json: median clip length, cut cadence (cuts/min via scene detection), intro/outro length, caption usage, zoom/punch-in frequency, music bed yes/no
- **Edit-style conventions (V4 — feeds the humor/meme mechanic):**
  additional style_profile section measuring HOW the references are edited:
  captions_per_min + median caption duration (frame-sampled OCR presence,
  best effort), zoom_events_per_min, sfx_events_per_min (audio transient/novelty
  detection outside music beds, best effort), cut_in_inserts_per_min
  (static-frame/meme insert detection via scene stats, best effort).
  Unmeasurable fields are null + flagged — never guessed.
- Profile is INPUT to Phases 12/13 AND to the phase-10 editorial prompts
  (the LLM imitates the reference edit density: how often to caption/zoom/SFX),
  schema-validated

## Concrete files
- src/pipeline/style.py, schemas/style_profile.schema.json, tests/harness/style_profile_check.py

## Tests / metrics
- style_profile_schema → style_profile_schema_valid == 1; phase_11_tests

## Real vs mock
- Runs on real reference files; scene detection via PySceneDetect/OpenCV.

## Human review criteria
- Profile matches what the user sees in the references (sanity read-through).

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 11 gate.
