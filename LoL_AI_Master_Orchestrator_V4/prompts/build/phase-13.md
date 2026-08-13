# BUILD PHASE 13 — Automatic Cut Rules

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
- Phase 12 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Highlights (incl. editorial data from phase 10: punchline_ts, category,
  callback_refs, zoom/sfx suggestions) + style profile

## Architecture
- Deterministic pre/post-roll per event type (kill 4 s/3 s, steal 8 s/4 s, reaction 2 s/4 s — config), clip length clamp 12–45 s, overlap merge, per-video chaptering for compilations
- Pure functions, no live LLM calls in this phase — but **editorial-aware**:
  - punchline-aware end: if punchline_ts present, clip end = punchline_ts +
    reaction decay window (config, default 2.5 s) instead of fixed post-roll,
    then clamped as usual
  - category-specific pre-roll (funny needs setup: config, default 6 s before
    first laugh onset; clutch: from fight start event)
  - callback handling: if a highlight has callback_refs, emit an optional
    callback_insert instruction (ref window, max 5 s) for the EDL layer;
    drop silently if the ref lies outside retained media
  - zoom/sfx suggestions are passed through (clamped to clip bounds), never
    invented here

## Tests / metrics
- cutrule_determinism → cut_determinism == 1, clip_len_violations == 0; phase_13_tests
  (editorial fields come from fixtures; rules stay pure functions ⇒ fully deterministic)

## Human review criteria
- 10 sampled clips start/end feel right (no cut mid-fight-start, no punchline
  cut off, funny clips include their setup).
## Concrete files
- src/pipeline/cutrules.py, tests/harness/cutrules_eval.py, config/cutrules.toml

## Failure modes
- overlapping highlight windows collapsing into one giant clip, event at segment boundary, pre-roll reaching before session start, style profile missing (fall back to defaults, flag in report)

## Real vs mock
- Fully deterministic/unit-testable; golden fixtures from 2 real sessions.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 13 gate.
