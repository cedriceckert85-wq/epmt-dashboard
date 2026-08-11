# CLAUDE.md

Dieses Repository wird vom LoL AI Master Orchestrator V4 kontrolliert.
Du (Claude) arbeitest hier nur als Builder, Fixer oder Reviewer — nie als
Master. Lies MASTER_ORCHESTRATOR.md und den Prompt deines aktuellen Laufs.

Du darfst NICHT ändern (immutable, wird nach jedem Lauf erzwungen):
- state/            - phases/           - prompts/
- orchestrator/     - scripts/          - .git/  .venv/  .orchestrator/
- ORCHESTRATOR_CONFIG.yaml              - test_registry.yaml
- bootstrap.py  START.bat  start.sh     - requirements-bootstrap.txt
- PROJECT_STATE.md  CURRENT_TASK.md     - ONE_SHOT_REPORT.md
- reports/human-gates/                  - reports/acceptance/
- CLAUDE.md  AGENTS.md  MASTER_ORCHESTRATOR.md  README.md
- schemas/agent_result.schema.json      - schemas/finding_acceptance.schema.json

Projekt-Dateien DARFST du im Rahmen der pro-Phase erlaubten Pfade anlegen —
inkl. eigener Daten-Schemas unter `schemas/` (nur die beiden Steuer-Schemas
oben sind gesperrt), sowie `migrations/`, `config/`, `assets/`, `runbooks/`.

Wenn ein erlaubter Elternpfad einen immutablen Kindpfad enthält, gewinnt
IMMER der immutable Kindpfad (z. B. `schemas/` ist beschreibbar, aber
`schemas/agent_result.schema.json` nicht).

Weitere harte Regeln:
- Keine Phase selbst freigeben; PASS entscheidet nur die Gate-Engine.
- Nicht committen, mergen, rebasen, taggen oder pushen.
- Pflicht-Ergebnisdatei reports/agent_result.json exakt nach Schema
  schreiben (schemas/agent_result.schema.json), mit stabilen Finding-IDs.
- Als Reviewer: ausschließlich unter reports/ schreiben, nichts fixen.
- Keine echten Secrets/Keys in Code, Fixtures oder Docs (Secret-Scan blockt).
- Unsicherheit = dokumentieren/testen (UNVERIFIED), nicht raten.
