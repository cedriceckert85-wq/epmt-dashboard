# High Finding Acceptance

Reviewer reports may contain HIGH findings but reviewers cannot self-accept them.

Canonical acceptance is external to the reviewer report.

Rules (V2.4):
- Every finding in an agent report MUST carry a stable unique `id` (schema-enforced).
- There is NO positional/index fallback. A HIGH finding without an id can never be accepted and always counts as unaccepted (fail closed).
- Acceptance records are orchestrator/human owned JSON files in `reports/acceptance/` (agent-immutable) and validate against `schemas/finding_acceptance.schema.json`. They are never part of an agent report and never written by agents.
- The gate engine loads and validates the records ITSELF (orchestrator/acceptance.py); a caller-supplied id set is not an input anymore. Invalid or stale records surface as gate reasons instead of being silently ignored.
- An acceptance record binds: phase, finding id, exact candidate SHA, decision, reason, approver, timestamp.
- Acceptance is SHA-scoped: a new candidate commit invalidates prior acceptances until explicitly re-issued.
- The gate engine receives only the set of externally accepted HIGH finding ids (`accepted_high_ids`).

`max_unaccepted_high` means exactly what it says: HIGH findings whose id is not present in that external acceptance set.

No acceptance field inside an agent report is authoritative or even schema-valid.
