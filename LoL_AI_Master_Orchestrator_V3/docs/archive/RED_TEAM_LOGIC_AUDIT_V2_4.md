# V2.4 Logic Audit Fixes

Addressed (third red-team pass):
1 Finding ids: `id` is now a required schema field on every finding; the order-dependent `index:N` fallback is removed; HIGH findings without id are always unaccepted (fail closed). Review prompts require a stable unique id.
2 HUMAN_GATE entry deadlock: approval record is only required for transitions to PASSED/MERGED. Entering HUMAN_GATE from GATE_EVALUATION no longer demands an approval that cannot exist yet. HUMAN_GATE->PASSED remains the only success path for human-gated phases.
3 `accepted_by`/`acceptance_reason` removed from the agent report schema. Acceptance records live in the new orchestrator-owned `schemas/finding_acceptance.schema.json`, bound to phase + finding id + exact SHA + approver.
4 Build artifacts (`__pycache__/`, `.pytest_cache/`) removed from the package; `.gitignore` added.
5 Process runner closes its pipe handles on the final fail-closed timeout path (no fd/handle leak across repeated timeouts). `cleanup_incomplete` semantics documented in docs/EXIT_CODES.md: mandatory BLOCKED, no automatic rerun.
6 `requirements-dev.txt` added (pytest, PyYAML, jsonschema) for the skeleton unit tests.

Verification in this package:
- unit tests cover: HUMAN_GATE entry without approval is legal; approval still required for PASSED; id-based acceptance is order-independent; findings without id cannot be accepted; agent schema rejects acceptance fields.
