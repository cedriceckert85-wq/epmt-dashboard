# LoL AI Master Orchestrator V2

This package is intentionally fail-closed.

It includes:
- real Phase 00 specification
- Python orchestrator skeleton
- Claude/Codex adapter skeletons
- deterministic gate engine
- canonical state model
- 21 phase configs
- build prompts
- adversarial review prompts
- fake-agent tests
- Obsidian/Git source-of-truth setup
- human-gate runbooks

The live orchestrator is NOT declared production-ready.
Phase 00 must implement, test and independently review the skeleton before enabling live autonomous execution.


## V2.3
Includes second red-team logic audit fixes.

## V2.4
Third red-team logic audit fixes.

## V3 (normative)
Structural refactor after external senior review:
- test_registry.yaml: every symbolic test mapped to command/timeout/requirements/parser/evidence
- self-validating acceptance store (reports/acceptance/, SHA- and phase-bound, gate loads+validates itself)
- gate engine split: validate_lifecycle_transition / evaluate_completion_gate / validate_merge_commit
- fully detailed Phase 01-20 build specs (inputs, architecture, files, data models, failure modes, tests, hard metrics, real-vs-mock, human review criteria)
- reference path-policy implementation with real security unit tests
Older audits live in docs/archive/ and are historical only. V3 is the single normative version.
