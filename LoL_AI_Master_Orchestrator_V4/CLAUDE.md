# CLAUDE.md

Dieses Repository wird vom LoL AI Master Orchestrator V4 kontrolliert.
Du (Claude) arbeitest hier nur als Builder, Fixer oder Reviewer — nie als
Master. Lies MASTER_ORCHESTRATOR.md und den Prompt deines aktuellen Laufs.

Du darfst NICHT ändern (immutable, wird nach jedem Lauf erzwungen):
- state/            - phases/           - schemas/
- prompts/          - orchestrator/     - .git/  .venv/  .orchestrator/
- ORCHESTRATOR_CONFIG.yaml              - test_registry.yaml
- bootstrap.py  START.bat  start.sh     - requirements-bootstrap.txt
- PROJECT_STATE.md  CURRENT_TASK.md     - ONE_SHOT_REPORT.md
- reports/human-gates/                  - reports/acceptance/
- CLAUDE.md  AGENTS.md  MASTER_ORCHESTRATOR.md  README.md

Wenn ein erlaubter Elternpfad einen immutablen Kindpfad enthält, gewinnt
IMMER der immutable Kindpfad.

Weitere harte Regeln:
- Keine Phase selbst freigeben; PASS entscheidet nur die Gate-Engine.
- Nicht committen, mergen, rebasen, taggen oder pushen.
- Pflicht-Ergebnisdatei reports/agent_result.json exakt nach Schema
  schreiben (schemas/agent_result.schema.json), mit stabilen Finding-IDs.
- Als Reviewer: ausschließlich unter reports/ schreiben, nichts fixen.
- Keine echten Secrets/Keys in Code, Fixtures oder Docs (Secret-Scan blockt).
- Unsicherheit = dokumentieren/testen (UNVERIFIED), nicht raten.
