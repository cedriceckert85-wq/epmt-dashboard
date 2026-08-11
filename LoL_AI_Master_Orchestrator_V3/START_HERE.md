# START HERE — LoL AI Master Orchestrator V2

## Wichtig
Diese V2 priorisiert Qualität, Nachweisbarkeit und Sicherheit vor Geschwindigkeit.

Der zentrale Unterschied:
Claude oder Codex sind NICHT der Master.
Ein deterministischer Python-Orchestrator koordiniert beide CLIs als getrennte Prozesse.

## Reihenfolge
1. Phase 00 Orchestrator bauen.
2. Fake-Agent-Tests vollständig bestehen.
3. Claude CLI separat smoke-testen.
4. Codex CLI separat smoke-testen.
5. Orchestrator-Cross-Review durchführen.
6. Human Gate für Phase 00.
7. Erst danach Phase 01 des LoL-Systems starten.

## Harte Regel
Eine AI-Aussage wie "PASS" oder "Looks good" darf niemals eine Phase freigeben.
PASS basiert auf:
- echten Test-Exit-Codes
- validierten Report-Schemas
- Messwerten
- Git-Integrität
- Security-Checks
- unabhängigen Review-Findings
- erforderlichen Human Gates

## Stop-Regel
Wenn etwas nicht verifiziert werden kann:
Status = UNVERIFIED / BLOCKED.
Nicht improvisieren.


## MVP Network
Before Phase 06, Tailscale must be installed on the Central PC and Streamer PC and validated with a real integration test.

Architecture:
Streamer Agent → Tailscale → Central Receiver.

No cloud storage or public router port is required for the MVP.

Tailscale does not replace resumable upload or application authentication.
