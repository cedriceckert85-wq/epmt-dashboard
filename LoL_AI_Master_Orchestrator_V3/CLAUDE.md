# CLAUDE.md

Dieses Repository wird vom LoL AI Master Orchestrator kontrolliert.

Du darfst NICHT direkt ändern:
- state/
- phases/
- schemas/
- ORCHESTRATOR_CONFIG.yaml
- .git/

Du darfst keine Phase selbst freigeben.
Du darfst nicht committen, mergen, rebasen, taggen oder pushen.

Lies MASTER_ORCHESTRATOR.md und den generierten Current Task.
Arbeite nur innerhalb der erlaubten Pfade.
Unsicherheit = dokumentieren/testen, nicht raten.


## Additional immutable control-plane paths
You must NOT modify:
- PROJECT_STATE.md
- CURRENT_TASK.md
- reports/human-gates/
- reports/acceptance/
- test_registry.yaml
These are orchestrator-owned projections/approval records.

If an allowed parent path contains an immutable child path, the immutable child path ALWAYS wins.
