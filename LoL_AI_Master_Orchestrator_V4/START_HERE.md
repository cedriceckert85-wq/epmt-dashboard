# START HERE — LoL AI Master Orchestrator V4 (One-Shot)

**Kurzfassung: Voraussetzungen aus README.md erfüllen, dann `START.bat`
(Windows) bzw. `./start.sh` (Linux/macOS) ausführen. Fertig.**

Claude oder Codex sind NICHT der Master. Ein deterministischer
Python-Orchestrator (mitgeliefert, selbst getestet) koordiniert beide CLIs
als getrennte Prozesse durch alle 21 Phasen.

## Was beim Start passiert
1. Bootstrap: Python/Git-Check, .venv, Abhängigkeiten, git init + Baseline.
2. Doctor: beide CLIs vorhanden + eingeloggt? Capabilities (GPU/Tailscale/…)?
3. Phase 00: Selbsttest des Orchestrators (komplette Unit-Testsuite).
4. Phasen 01–20: Builder (Claude/Codex im Wechsel) → echte Tests →
   Checkpoint-Commit → Review durch den anderen Anbieter → deterministisches
   Gate → ff-only Merge. Fehler: max. 2 Fix-Zyklen, dann BLOCKED.

## Harte Regeln (unverändert)
Eine AI-Aussage wie „PASS" oder „Looks good" gibt niemals eine Phase frei.
PASS basiert ausschließlich auf: echten Test-Exit-Codes, validierten
Report-Schemas, Messwerten, Git-Integrität, Secret-Checks, unabhängigen
Review-Findings und (auto- oder human-)Gate-Records mit exakter SHA-Bindung.

## Stop-Regel
Nicht verifizierbar ⇒ UNVERIFIED / BLOCKED. Es wird nicht improvisiert.
Stoppen: Strg+C. Fortsetzen: START erneut ausführen (Resume ist eingebaut).

## Details
- README.md — Bedienung, Kommandos, Kosten/Dauer
- MASTER_ORCHESTRATOR.md — normative Regeln
- docs/V4_CHANGES.md — was V4 gegenüber V3 angepasst hat und warum
