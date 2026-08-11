# BUILD PHASE 11 — Reference Style

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 10 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- 3–5 reference videos/channels (user-provided files/links), sample own footage

## Architecture
- Style profile extractor → style_profile.json: median clip length, cut cadence (cuts/min via scene detection), intro/outro length, caption usage, zoom/punch-in frequency, music bed yes/no
- Profile is INPUT to Phases 12/13 (cut rules + EDL prompts), schema-validated

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
