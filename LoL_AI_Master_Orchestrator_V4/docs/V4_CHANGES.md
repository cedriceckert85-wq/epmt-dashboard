# V4 — One-Shot Edition: Änderungen gegenüber dem V3-Plan

Ziel der Anpassung: **eine** ausführbare Aktion (`START.bat` / `start.sh`),
danach bauen Claude CLI und Codex CLI das Programm gemeinsam und autonom —
ohne die Fail-Closed-Substanz von V3 aufzugeben.

## 1. Der Orchestrator wird mitgeliefert (Henne-Ei gelöst)
V3: Phase 00 = „Claude baut den Orchestrator" — d. h. das Paket war ohne
manuelle Vorarbeit nicht lauffähig.
V4: Der Orchestrator ist **fertig implementiert und selbst getestet**
(79 Unit-Tests, inkl. End-to-End-Dry-Run der gesamten Schleife).
Phase 00 ist jetzt der **Selbsttest-Gate**: Doctor + komplette Testsuite
müssen grün sein, bevor irgendein Agent startet (`agentless: true`).

## 2. Ein Einstiegspunkt
Neu: `START.bat` / `start.sh` → `bootstrap.py` (nur Standardbibliothek):
Python/Git-Check → `.venv` + pinned Deps → `git init` + Baseline-Commit →
`python -m orchestrator run`. Idempotent: erneutes Starten **setzt fort**
(Resume aus `state/project_state.json` + Journal).

## 3. Human Gates: auto (Standard) vs. strict
V3 verlangte an 12 Phasen echte menschliche Freigaben — unvereinbar mit
„einmal ausführen". V4 führt `execution.gate_mode` ein:
- **auto** (Default): Der Orchestrator schreibt ein SHA-gebundenes
  AUTO_GATE-Approval — aber erst, nachdem *alle* deterministischen
  Kriterien (Tests, Review, Secret-Scan, SHA-Invarianten) bereits erfüllt
  sind. Die Lifecycle-Sequenz GATE_EVALUATION→HUMAN_GATE→PASSED bleibt.
- **strict** (`--strict-gates`): V3-Verhalten, Lauf pausiert bis
  `orchestrator approve`.

## 4. Hardware-/Netzwerk-Tests: deferred statt Dead-End
V3: unerfüllte Requirements ⇒ UNVERIFIED ⇒ faktisch Stopp (auf einem
Rechner ohne Tailscale/GPU/OBS wäre nie eine spätere Phase erreichbar).
V4: Solche Tests sind pro Phase explizit als `deferrable_tests` markiert.
Bei fehlender Capability werden sie als **UNVERIFIED/deferred**
protokolliert (Journal, Phase-History, Abschlussbericht) — **niemals als
PASS**. Metriken, die nur aus deferred Tests stammen, werden mit
deferred. Der 8h-Soak bekommt zusätzlich das Requirement `long_run`
(bewusstes Opt-in via `capabilities_override`). Alle Mock-/Fixture-Tests
bleiben harte Pflicht.

## 5. Reviewer „read-only" präzisiert
V3 verlangte einen komplett schreiblosen Reviewer, brauchte aber
gleichzeitig ein strukturiertes Ergebnis. V4: Der Reviewer darf **nur**
sein Resultat unter `reports/` schreiben; das wird nach dem Lauf in die
Artefakte verschoben und aus dem Worktree entfernt (Review-Evidence landet
nie in der Git-History). Jeder andere Write wird revertiert + protokolliert;
beim zweiten Verstoß: BLOCKED.

## 6. Enforcement in zwei Schichten
- **Git-Diff-Inspektion** nach jedem Agent-Lauf gegen die Pfad-Policy
  (immutable schlägt allowed; Referenzimplementierung aus V3 unverändert).
- **Neu: Hash-Snapshots** für git-ignorierte Kontrolldateien (`state/`,
  `reports/human-gates/`, `reports/acceptance/`, generierte Projektionen):
  Git-Status ist dort blind, der Snapshot-Vergleich nicht. Manipulation ⇒
  Rollback + BLOCKED.
- Immutable-Liste erweitert um `orchestrator/`, `prompts/`, `bootstrap.py`,
  Start-Skripte und `.orchestrator/` (in V3 war `orchestrator/` beschreibbar,
  weil Phase 00 ihn erst bauen sollte).

## 7. Git-Modell vereinfacht
V3 sah Worktrees vor. V4 nutzt pro Phase einen Kandidaten-Branch
(`phase/NN`) im einzigen Checkout; Merge in `main` nur `--ff-only` und
SHA-verifiziert (tested == reviewed == approved == merged). Für strikt
sequenzielle Phasen ist das äquivalent und deutlich robuster über
Windows/macOS/Linux hinweg.

## 8. Laufzeit-State raus aus Git
`state/`, Projektionen (`PROJECT_STATE.md`, `CURRENT_TASK.md`),
Gate-/Acceptance-Records und Artefakte sind gitignored. Grund: Ein
Approval, das nach dem Kandidaten-Commit committet würde, änderte die SHA,
an die es gebunden ist (ungelöste V3-Subtilität). Kanonisch bleiben
`state/project_state.json` + `state/journal.jsonl` + Git-SHAs; Records
bleiben agent-immutable via Snapshot-Enforcement.

## 9. Agent-Ergebnis-Kontrakt konkretisiert
Agenten schreiben `reports/agent_result.json` (Schema unverändert aus V3).
Der Orchestrator validiert selbst (ohne jsonschema-Abhängigkeit), erzwingt
stabile, eindeutige Finding-IDs, archiviert das File in die Artefakte und
hält es aus der Git-History heraus. Ungültig ⇒ 1 korrigierender Retry ⇒
sonst BLOCKED.

## 10. Lifecycle-Erweiterung
Neu erlaubt: `GATE_EVALUATION→FIXING` und `RETESTING→FIXING` (Gate-Fehler
durch Findings/Tests führen in den Fix-Zyklus statt hart zu blocken).
Alle V3-Verbote bleiben: kein BUILDING→PASSED, kein REVIEWING→MERGED,
Human-Gate-Phasen nur über HUMAN_GATE→PASSED, max. 2 Fix-Zyklen.

## 11. CLI-Flags konfigurierbar
Claude-/Codex-Aufrufparameter liegen in `ORCHESTRATOR_CONFIG.yaml`
(`agents.*.args`) und sind ohne Codeänderung anpassbar, falls sich die
CLIs ändern. Der Doctor macht vor dem Lauf echte `--version`- und
Login-Smoke-Checks (abschaltbar mit `--skip-smoke`).

## Unverändert aus V3 (normativ übernommen)
Gate-Engine-Split, Acceptance-Store (SHA- und phasengebunden, selbst
validierend), Test-Registry als einzige Quelle vertrauenswürdiger
Exit-Codes/Metriken, Pfad-Policy-Referenzimplementierung, Prozess-Runner
mit Tree-Kill + `cleanup_incomplete`-Fail-Closed, Cross-Vendor-Pflicht
(Builder ≠ Reviewer, nie Fake-Review), Secret-Strip in Test-Umgebungen,
21 Phasen + Build-Prompts + Adversarial-Review-Prompts.
