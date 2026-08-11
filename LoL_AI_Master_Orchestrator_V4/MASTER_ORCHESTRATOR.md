# MASTER ORCHESTRATOR (V4 — normativ)

## Rolle
Deterministisches Control Plane für Claude Code CLI und Codex CLI.
Der Orchestrator wird in diesem Paket **fertig mitgeliefert** und validiert
sich in Phase 00 selbst (Doctor + komplette Unit-Testsuite).

## Wahrheitsquellen
Kanonisch:
- state/project_state.json
- state/journal.jsonl
- Git commit SHA

Generiert aus kanonischem State (nie Input):
- state/current_task.json
- PROJECT_STATE.md
- CURRENT_TASK.md

## Rollen
Builder: implementiert (Claude oder Codex, laut Phase).
Tester: deterministische Registry-Kommandos, kein LLM-Gate.
Reviewer: der jeweils andere Anbieter; darf nur sein Resultat unter
reports/ schreiben (wird archiviert und aus dem Worktree entfernt).
Fixer: behebt nur verifizierte Findings/Testfehler (gleicher Anbieter wie Builder).
Human Approver: nur im strict-Modus erforderlich; im auto-Modus ersetzt ein
SHA-gebundenes AUTO_GATE-Record die manuelle Freigabe — erst NACHDEM alle
deterministischen Kriterien erfüllt sind.

## Lifecycle
READY → BUILDING → TESTING → CHECKPOINTED → REVIEWING
→ GATE_EVALUATION → HUMAN_GATE (falls human_gate) → PASSED → MERGED

Fehlerpfad: TESTING/RETESTING/REVIEWING/GATE_EVALUATION → FIXING →
RETESTING → CHECKPOINTED → …  (max. 2 Fix-Zyklen, dann BLOCKED)

Unklar/unverifizierbar: BLOCKED (fail closed, resumierbar).

Illegale Sprünge (werden von validate_lifecycle_transition abgewiesen):
BUILDING→PASSED, REVIEWING→MERGED, GATE_EVALUATION→PASSED bei
human_gate-Phasen, HUMAN_GATE→MERGED.

## PASS nur wenn
- alle required tests exit 0 sind (deferrable Tests dürfen stattdessen als
  UNVERIFIED/deferred protokolliert sein — niemals als PASS)
- alle Metriken in Grenzwerten (deferred-only-Metriken werden mit-deferred)
- keine Blocker-Findings, keine unakzeptierten High-Findings
- keine verbotenen Dateiänderungen, kein Secret-Scan-Finding
- Worktree sauber
- tested SHA == reviewed SHA == approved SHA == merged SHA
- Human-Gate-Record vorhanden (auto oder strict), exakt SHA-gebunden

## Agenten dürfen nie
- state/, phases/, schemas/, prompts/, orchestrator/, test_registry.yaml,
  ORCHESTRATOR_CONFIG.yaml, bootstrap.py, Start-Skripte ändern
- reports/human-gates/ oder reports/acceptance/ schreiben
- committen, mergen, rebasen, taggen, pushen (.git ist immutable)
- Human Gates oder Acceptance-Records erzeugen
- sich selbst als unabhängigen Reviewer ausgeben

Enforcement: Git-Diff-Inspektion (Pfad-Policy: immutable schlägt allowed)
UND Hash-Snapshots für git-ignorierte Kontrollpfade — nach jedem Agent-Lauf.
Verstöße werden revertiert und journaliert; Wiederholung ⇒ BLOCKED.

## Reviewer
Nur reports/-Writes erlaubt (Resultatdatei). Alles andere wird revertiert;
zweiter Verstoß ⇒ BLOCKED. Kein Fake-Review: Ist der andere Anbieter nicht
verfügbar, meldet der Doctor NOT READY und es startet kein Lauf.

## Fix-Loops
Maximal 2 automatische Fix-Zyklen pro Phase, danach BLOCKED + Bericht
(ONE_SHOT_REPORT.md). Wiederanlauf via START (Resume), `unblock` oder
`reset-phase`.

## Cross-Vendor
Builder und Reviewer sind in jeder Agent-Phase unterschiedliche Anbieter
(phases/*.yaml, validiert beim Laden).

## Test Registry
Jeder symbolische Test in phases/*.yaml MUSS in test_registry.yaml stehen
(command, timeout, requirements, parser, evidence). Nur registry-erzeugte
Exit-Codes/Metriken erreichen das Gate. Unerfüllte Requirements ⇒
UNVERIFIED; nur explizit deferrable Tests dürfen deferred werden.
Junit-Evidence mit 0 Tests gilt als FAIL (Schutz gegen „grüne" Leerläufe).

## Gate-Engine-Split (unverändert V3)
- validate_lifecycle_transition(): reine Übergangslegalität
- evaluate_completion_gate(): einzige PASS-Entscheidung
- validate_merge_commit(): PASSED→MERGED SHA-Identität

## High-Finding-Acceptance (unverändert V3)
Extern, id-basiert, SHA-gebunden (docs/FINDING_ACCEPTANCE.md,
schemas/finding_acceptance.schema.json), Records in reports/acceptance/
(agent-immutable), vom Gate selbst geladen und validiert.

## MVP Network — Tailscale (unverändert V3)
Streamer Agent → Tailscale → Central Receiver. Tailscale ersetzt weder
App-Auth noch Tenant-Isolation, resumable Upload, Checksums, Idempotenz,
Queue oder Rate-Limiting. Kein automatischer Public-Fallback. Ohne
Tailscale-Capability laufen die betroffenen Tests als deferred/UNVERIFIED
(siehe docs/TAILSCALE_NETWORK.md, runbooks/).
