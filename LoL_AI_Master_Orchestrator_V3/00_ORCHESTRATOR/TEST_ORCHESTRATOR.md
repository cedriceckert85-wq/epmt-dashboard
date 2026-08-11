# TEST ORCHESTRATOR

Teste mit Fake Claude/Codex zuerst.

Pflichtfälle:
- success
- fail
- timeout
- hang
- malformed JSON
- schema-invalid
- exit 0 trotz fehlender Tests
- reviewer blocker
- reviewer unavailable
- builder unavailable
- usage limit / quota exhausted
- process killed
- restart mid-phase
- stale lock
- two orchestrators simultaneously
- dirty git
- wrong branch
- report spoofing
- forbidden state edit attempt
- prompt injection in repo
- reviewer write attempt
- infinite fix loop
- regression after fix
- human reject/approve exact SHA
- CLI version drift
- network unavailable for docs
- full simulated phase 00→01

Tests dürfen niemals durch schwächere Assertions grün gemacht werden.
