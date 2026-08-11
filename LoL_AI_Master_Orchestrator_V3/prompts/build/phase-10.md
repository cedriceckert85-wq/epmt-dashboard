# BUILD PHASE 10 — Highlight Ranking

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 09 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- riot_events, reaction events, sync maps

## Architecture
- Pure-function scorer (no LLM): weights table in config — multikill (Double 2 … Penta 10), shutdown 3, objective steal 6, baron/elder 4, first blood 3, own death −1; reaction co-occurrence within ±8 s multiplies 1.5×
- Windowing: event clusters merged if gaps < 10 s; top-N per hour (config, default 6) + global top-K
- Deterministic: same inputs ⇒ identical ordering (stable tiebreak by t0)
- Output highlight rows with reason_json (which signals fired)

## Concrete files
- src/pipeline/rank.py, tests/harness/rank_eval.py, tests/fixtures/ranking/labels.json (hand-picked best moments from ≥ 2 real sessions)

## Tests / metrics
- ranking_determinism → rank_determinism == 1
- ranking_precision_fixture → precision_at_10_fixture ≥ 0.6 vs hand labels
- phase_10_tests

## Real vs mock
- Labels from real sessions; scorer itself fully unit-testable.

## Human review criteria
- Reason strings understandable; weight table documented and easy to tune.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 10 gate.
