# Phase 00 — Implementation Report (Master Orchestrator)

Status: **implementiert, getestet, adversarial reviewed, fix-verifiziert.**
Der finale Freigabe-Entscheid bleibt der menschliche Phase-00-Human-Gate
(`runbooks/PHASE_00_GO_NO_GO.md`) — genau wie es die Spezifikation verlangt.

## Was gebaut wurde (gegen ORCHESTRATOR_SPEC.md)

| Spec-Anforderung | Modul |
|---|---|
| Python CLI | `orchestrator/main.py` (doctor/status/run-phase00/run/approve/unlock/recover) |
| Claude-/Codex-Adapter | `orchestrator/adapters/{claude,codex,fake}.py` |
| Prozessisolation, Timeouts, Child-Kill | `orchestrator/process_runner.py` |
| stdout/stderr-Capture, struktur. Validierung | `orchestrator/result_validation.py` |
| Prompt-Routing, Builder/Tester/Reviewer/Fixer | `orchestrator/engine.py` |
| deterministische Gate-Engine | `orchestrator/gates.py` (Skeleton, unverändert) |
| kanonischer State-Store + Markdown-Projektionen | `orchestrator/state_store.py` |
| Git-Worktree/Checkpoint/Merge | `orchestrator/gitops.py` |
| Single-Writer-Lock | `orchestrator/lock.py` |
| Allowed-Path-Enforcement | `orchestrator/path_policy.py` (Skeleton) + Engine-Diff-Check |
| Secret-Scan | `orchestrator/secret_scan.py` |
| Human-Gates | `orchestrator/human_gate.py` |
| Retry-Policy | Engine (`backoff`, `invalid_schema_retries`, `max_fix_cycles`) |
| Crash-Recovery, sicherer Rollback | `engine.recover()` |
| CLI-Version-Doctor | `orchestrator/doctor.py` |
| Dry-Run / Fake-Agent-Modus | `orchestrator/simulate.py`, `adapters/fake.py` |
| Audit-Log | `orchestrator/journal.py` |
| Tailscale-Preflight (Doctor-Hook) | `orchestrator/doctor.py` (`detect_capabilities`) |

## Verifikation

- **152 Unit-/Integrationstests** grün (`pytest tests/unit`), decken die
  Pflichtmatrix aus `TEST_ORCHESTRATOR.md` ab (success/fail/timeout/hang/
  malformed/schema-invalid/quota, reviewer unavailable, report spoofing,
  forbidden state edit, reviewer write, infinite fix loop, regression,
  human approve/reject exact SHA, restart mid-phase, stale lock, zwei
  Orchestratoren, dirty git, wrong branch, prompt injection, volle
  simulierte Phase 00→01).
- **Soak-Harness** (`tests/soak/run_8h_soak.py`): 2000 seed-deterministische
  Iterationen, 0 Invariantenverletzungen (Gate false-pass/false-block,
  Transition-Legalität, State-Persistenz).
- **`run-phase00`-Simulation**: kompletter Pipeline-Durchlauf in einem
  hermetischen Repo-Klon → **MERGED**.
- **Adversarialer Cross-Review** (6 Dimensionen, 22 Agenten,
  Skeptiker-Verifikation pro Finding): 10 bestätigte Findings, alle
  behoben und mit Regressionstests abgesichert; 6 Findings als nicht real
  widerlegt.

## Behobene Review-Findings

GIT-INTEGRITY-01 (Blocker, Rename maskiert Löschung immutabler Dateien),
RW-INJ-02 (gefälschte Freigaben via Worktree-Escape), CONC-01 (Lock-Race),
CONC-02/03 (Crash-Recovery zwischen Merge und State-Write), CONC-04
(Lost-Update in recover), SECENV-02/03/04/05 (Secret-Scan Fail-Closed,
Redaction). Details siehe Commit-Historie.

## Der Codex-Part (offene Frage des Betreibers)

Der Codereviewer-Slot ist bewusst herstellerunabhängig gebaut. Es gibt
drei Wege, den Codex-Part zu betreiben:

1. **Echte Codex-CLI** (Spec-konform, empfohlen für Produktion): OpenAI
   Codex CLI installieren (`npm i -g @openai/codex`), `codex login`,
   dann validiert `orchestrator doctor` automatisch Verfügbarkeit,
   `codex exec`-Flags (`--sandbox`, `--output-last-message`) und die
   Version. Ohne verifizierte CLI bleiben Live-Phasen fail-closed BLOCKED.
2. **Anderer Zweit-Anbieter als Reviewer**: Da nur *cross-vendor*
   (Builder-Provider ≠ Reviewer-Provider) erzwungen wird, kann statt Codex
   jede zweite CLI als unabhängiger Reviewer dienen. Dafür einen neuen
   Adapter analog `adapters/codex.py` (doctor + run mit read-only Sandbox)
   ergänzen und in `ORCHESTRATOR_CONFIG.yaml`/`phase-*.yaml` als `reviewer`
   eintragen.
3. **Fake-Reviewer nur für Bootstrap/Tests**: `--fake-agents` nutzt den
   prozessbasierten Fake-Adapter. Ausschließlich für Phase-00-Bootstrap
   und CI — niemals als echter unabhängiger Review für Live-Phasen.

Bis eine echte zweite Hersteller-CLI verifiziert ist, laufen die
Live-Phasen 01–20 nicht scharf — das ist beabsichtigtes Fail-Closed-
Verhalten, kein Fehler.
