# MASTER ORCHESTRATOR

## Rolle
Deterministisches Control Plane für Claude Code CLI und Codex CLI.

## Wahrheitsquellen
Kanonisch:
- state/project_state.json
- state/journal.jsonl
- Git commit SHA

Generiert aus kanonischem State:
- state/current_task.json
- PROJECT_STATE.md
- CURRENT_TASK.md

## Rollen
Builder: implementiert.
Tester: deterministische Commands/Fault Harness, kein LLM-Gate.
Reviewer: anderer Anbieter, read-only.
Fixer: behebt nur verifizierte Findings.
Researcher: darf recherchieren/analysieren, aber weder schreiben noch Gates beeinflussen.
Human Approver: reale/irreversible Gates.

## Lifecycle
READY
→ BUILDING
→ TESTING
→ CHECKPOINTED
→ REVIEWING
→ GATE_EVALUATION
→ HUMAN_GATE (falls nötig)
→ PASSED
→ MERGED

Fehler:
FIXING → RETESTING → CHECKPOINTED → REVIEWING

Unklar:
BLOCKED

Illegale Sprünge:
BUILDING→PASSED
REVIEWING→MERGED
HUMAN_GATE→MERGED ohne exakte Commit-Freigabe

## PASS nur wenn
- alle required tests exit 0
- alle Metriken in Grenzwerten
- keine Blocker
- keine unakzeptierten High Findings
- keine verbotenen Dateiveränderungen
- kein Secret Scan Finding
- tested SHA == reviewed SHA == approved SHA == merged SHA
- Human Gate vorhanden, wenn erforderlich

## Agenten dürfen nie
- state/ ändern
- phases/ ändern
- schemas/ ändern
- Gate-Regeln ändern
- .git manipulieren
- Human Gates erzeugen
- sich selbst als unabhängigen Reviewer ausgeben

## Reviewer
Read-only. Wenn Reviewer Dateien verändert: BLOCKED.

## Fix-Loops
Maximal 2 automatische Fix-Zyklen.
Danach Human Escalation.

## Cross-Vendor
Kritische Phasen: Builder und Reviewer müssen unterschiedliche Anbieter sein.
Ist der andere Anbieter nicht verfügbar: WAITING/UNVERIFIED, niemals Fake-Review.


## MVP Network Decision — Tailscale

For phases 00–08 the default network path is:

Streamer Agent → Tailscale private tunnel → Central Receiver.

Tailscale is only the network/tunnel layer. It does NOT replace:
- app/device authentication
- tenant isolation
- resumable/chunked upload
- checksums
- idempotency
- persistent queue
- adaptive rate limiting

No automatic public fallback is allowed.
If Tailscale is unavailable, upload pauses and queues locally.

For the MVP, router port-forwarding is not required.

See:
- docs/TAILSCALE_NETWORK.md
- runbooks/TAILSCALE_ONBOARDING.md
- runbooks/TAILSCALE_FIREWALL.md


## Path precedence rule
Immutable paths override allowed write paths.

Example:
- `reports/` may be writable for normal reports.
- `reports/human-gates/` is immutable to agents.
Therefore an agent may write `reports/phase-04.md` but may NOT create or alter anything under `reports/human-gates/`.

The orchestrator must enforce this after every agent run by diff inspection.


## Human-gate lifecycle
For a phase with `human_gate: true`, the only valid success path is:

GATE_EVALUATION → HUMAN_GATE → PASSED → MERGED

A direct GATE_EVALUATION → PASSED transition is rejected for human-gated phases even if an approval record exists.


## High-finding acceptance
Acceptance is external, id-based and SHA-bound (docs/FINDING_ACCEPTANCE.md, schemas/finding_acceptance.schema.json).
Acceptance records live in reports/acceptance/ (agent-immutable). The gate engine loads and validates the records itself (phase + finding id + exact candidate SHA + decision); a pre-built id set is no longer accepted as input. Agents never write acceptance records. Findings without a stable id are always unaccepted.

## Test registry
Every symbolic test in phases/*.yaml MUST have an entry in test_registry.yaml (command, timeout, requirements, parser, evidence artifact). The gate engine only trusts exit codes/metrics produced by registry-executed commands. Unmet hardware/network requirements => UNVERIFIED, never skipped-as-pass. The registry is agent-immutable.

## Gate engine split
- validate_lifecycle_transition(): pure transition legality, safe for every transition (BUILDING->TESTING etc.)
- evaluate_completion_gate(): PASS decision only (tests, metrics, findings, SHAs, human approval)
- validate_merge_commit(): PASSED->MERGED SHA identity
evaluate_completion_gate must never be called for early transitions.
