# BUILD PHASE 10 — Highlight Ranking (Signal Core + LLM Editorial Brain)

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 09 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- riot_events, reaction events, word-timestamped transcripts (phase 09), sync maps
- claude CLI (claude -p, Max subscription) available at RUNTIME on the pipeline
  machine — never inside test environments (provider secrets are stripped there)

## Architecture — two layers, deterministic core + semantic brain

### Layer 1: Signal scorer (deterministic safety net, unchanged V3)
- Pure-function scorer: weights table in config — multikill (Double 2 … Penta 10),
  shutdown 3, objective steal 6, baron/elder 4, first blood 3, own death −1;
  reaction co-occurrence within ±8 s multiplies 1.5×
- Windowing: event clusters merged if gaps < 10 s
- Deterministic: same inputs ⇒ identical ordering (stable tiebreak by t0)

### Layer 2: LLM Editorial Brain (V4 — THE quality mechanic)
This layer is what turns "event compilation" into "entertaining video".
- src/pipeline/editorial.py: builds a session timeline document (word-timestamped
  transcript merged with riot/reaction events, mono_ns-mapped) and queries the LLM
  (claude -p, strict JSON output) in TWO passes:
  1. **Session pass** (whole session, chunked with running summary if needed):
     narrative arcs, running gags, callback pairs ("moment X is funny because of
     moment Y at t=…"), emotional beats. Output: session_context.json.
  2. **Moment pass** (per candidate window from Layer 1 PLUS up to K
     LLM-discovered windows that have NO game event — pure comedy/talk moments):
     {t0_adj, t1_adj, semantic_score 0–10, category [funny|hype|fail|clutch|
     callback|wholesome], punchline_ts, callback_refs[], title_suggestion,
     sfx_suggestions[{ts,kind}], zoom_suggestions[{ts,duration_ms}], reason}
- Final score = w_signal·signal + w_semantic·semantic (config, default 0.4/0.6);
  LLM-discovered windows enter ranking with signal=0. Top-N per hour + global
  top-K as before; reason_json now carries both layers' reasons.
- **Personalization inputs (loaded into the editorial prompts when present,
  both schema-validated, both optional):** humor_profile.json (few-shot
  examples from the phase-14 dashboard ratings — the user's own humor) and
  style_profile.json edit conventions (phase 11 — caption/zoom/SFX density
  of the reference channels). Absence ⇒ neutral defaults, flagged in report.
- Also build tests/harness/editorial_eval.py: offline eval tool comparing
  editorial output against hand-labeled funny moments of a session
  (found-rate, median |punchline_ts − label|). Not part of gated tests
  (needs live LLM); used at phase 14/20 human reviews.
- **Contract discipline**: every LLM response validated against
  schemas/editorial.schema.json; invalid ⇒ one retry ⇒ signal-only fallback for
  that item, flagged in reason_json. The pipeline NEVER blocks on the LLM.
- **Cost/robustness**: response cache keyed by content hash; config caps
  (max session-pass tokens, max moment calls per session); model/CLI args in
  config/editorial.toml; missing CLI/quota ⇒ signal-only mode, clearly flagged.

### Determinism scope (do not weaken, do not blur)
rank_determinism == 1 applies to: Layer 1 alone AND the merge function given a
FIXED editorial fixture (mock LLM). Live LLM output is not deterministic and is
therefore never part of the gated determinism test.

## Concrete files
- src/pipeline/rank.py, src/pipeline/editorial.py, src/pipeline/llm_client.py
  (CLI-subprocess wrapper w/ timeout+JSON extraction; mockable), config/editorial.toml,
  schemas/editorial.schema.json, tests/harness/rank_eval.py,
  tests/phase10/ (incl. mock-LLM contract tests: valid, invalid→retry→fallback,
  cache hit, discovered-window merge), tests/fixtures/ranking/labels.json
  (hand-picked best moments from ≥ 2 real sessions),
  tests/fixtures/editorial/ (canned LLM responses)

## Failure modes
- LLM invents timestamps outside session bounds (clamp + reject), quota mid-run
  (fallback), transcript gaps (LLM must see gap markers, not silence-as-boring),
  callback_refs pointing at cut-away moments (EDL layer must resolve or drop)

## Tests / metrics
- ranking_determinism → rank_determinism == 1 (scope above)
- ranking_precision_fixture → precision_at_10_fixture ≥ 0.6 vs hand labels
  (signal+mock-editorial path)
- phase_10_tests (incl. editorial contract tests with mock LLM — NEVER live keys)

## Real vs mock
- All gated tests mock the LLM (secrets are stripped from test envs by design).
- Live LLM quality is validated at the phase 14 dashboard / phase 20 POC human
  reviews, not by automated gates.

## Human review criteria
- Reason strings understandable (both layers); weights and editorial config easy
  to tune; fallback path visibly flagged; discovered no-event comedy windows
  actually appear in top-K on the fixture session.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 10 gate.
