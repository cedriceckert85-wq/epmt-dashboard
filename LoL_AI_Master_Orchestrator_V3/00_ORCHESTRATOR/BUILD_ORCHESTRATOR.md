# BUILD ORCHESTRATOR

Baue zuerst den Python Master Orchestrator gemäß ORCHESTRATOR_SPEC.md.

Arbeite in kleinen Teilaufgaben:
1. models/config/state
2. process runner
3. fake agents
4. Claude adapter
5. Codex adapter
6. git/worktree
7. deterministic test runner
8. gate engine
9. human gates
10. security
11. recovery
12. CLI
13. dry-run
14. integration tests

Nach jedem Teil:
- Unit Tests
- keine Gate-Abkürzungen
- keine Provider-Annahmen ohne Doctor/Capability Check

Live-Ausführung muss bis zum vollständigen Phase-00-Gate fail-closed bleiben.
