# LoL AI Master Orchestrator V4 — One-Shot Edition

**Einmal starten. Claude und Codex bauen das Programm zusammen.**

Ein deterministischer Python-Orchestrator (kein LLM!) steuert die
Claude Code CLI und die Codex CLI als getrennte Prozesse durch alle
21 Bauphasen des LoL-AI-Cutters — mit echten Tests, Cross-Vendor-Review,
Secret-Scans, Git-Checkpoints und fail-closed Gates.

---

## Voraussetzungen (einmalig, ~10 Minuten)

1. **Python 3.10+** — https://python.org
   (Windows-Installer: Haken bei „Add python.exe to PATH" setzen)
2. **Git** — https://git-scm.com/downloads
3. **Claude Code CLI** installiert **und eingeloggt**:
   `npm install -g @anthropic-ai/claude-code`, dann einmal `claude` starten
   und einloggen.
4. **Codex CLI** installiert **und eingeloggt**:
   `npm install -g @openai/codex`, dann einmal `codex` starten und einloggen.
5. Diese ZIP in einen **eigenen, leeren Ordner** entpacken (nicht in ein
   bestehendes git-Repository).

## Start (der eine Klick)

- **Windows:** `START.bat` doppelklicken.
- **Linux/macOS:** `./start.sh`

Das war's. Der Bootstrap prüft alles (Doctor), richtet eine virtuelle
Umgebung ein, initialisiert git und startet dann den Phasen-Lauf:

```
Phase 00  Orchestrator-Selbsttest (79 Unit-Tests müssen grün sein)
Phase 01  Architektur/Datenmodell     (Builder: Codex,  Reviewer: Claude)
Phase 02  OBS Agent                   (Builder: Claude, Reviewer: Codex)
…
Phase 20  POC / Go-No-Go
```

Pro Phase läuft immer derselbe deterministische Zyklus:

```
BUILDING → TESTING → CHECKPOINTED → REVIEWING → GATE → MERGED
                ↘ FIXING → RETESTING ↗   (max. 2 Fix-Zyklen)
```

- **Builder** (Claude *oder* Codex) implementiert die Phase.
- Der Orchestrator committet den Kandidaten und führt die **echten
  Test-Kommandos** aus `test_registry.yaml` aus (Secrets werden aus der
  Test-Umgebung entfernt).
- Der **Reviewer** (immer der *andere* Anbieter) prüft read-only und
  liefert Findings mit stabilen IDs.
- Das **Gate** entscheidet deterministisch: Test-Exit-Codes, Metriken,
  Blocker/High-Findings, Secret-Scan, SHA-Identität. Kein LLM kann eine
  Phase freigeben.
- Merge nur ff-only und nur bei PASS.

## Wichtig zu wissen

- **Dauer & Kosten:** Ein kompletter Lauf sind viele Stunden Agent-Arbeit
  und entsprechend API-/Abo-Nutzung bei Anthropic und OpenAI. Du kannst
  jederzeit mit `Strg+C` stoppen — **erneutes Starten setzt exakt dort
  fort** (Zustand liegt in `state/`).
- **BLOCKED ist Absicht:** Wenn etwas nicht verifizierbar ist oder 2
  Fix-Zyklen nicht reichen, stoppt der Lauf fail-closed. `ONE_SHOT_REPORT.md`
  sagt genau warum. Danach: Ursache beheben und START erneut ausführen,
  oder `python -m orchestrator reset-phase` / `unblock`.
- **Hardware-Tests werden nie gefaked:** Tests, die GPU, Tailscale, OBS,
  ein echtes Riot-Spiel oder den 8h-Soak brauchen, werden auf Maschinen
  ohne diese Fähigkeiten als **UNVERIFIED/deferred** protokolliert (siehe
  Abschlussbericht) — niemals als bestanden gemeldet. Auf dem Ziel-PC mit
  RTX 2080 + Tailscale laufen sie automatisch mit.
- **Human Gates:** Standard ist der One-Shot-Modus (`gate_mode: auto`):
  Freigaben werden automatisch erteilt, aber **nur** wenn vorher alle
  deterministischen Kriterien erfüllt sind, und als SHA-gebundene
  AUTO_GATE-Records dokumentiert. Wer die V3-Disziplin will:
  `START.bat --strict-gates` — dann pausiert der Lauf an jedem Human Gate.

## Nützliche Kommandos

```
START.bat                        # Lauf starten / fortsetzen (eine Aktion)
START.bat --strict-gates         # mit echten Human Gates
START.bat --phases 00-05         # nur bestimmte Phasen
START.bat doctor                 # nur Preflight-Checks
START.bat status                 # kanonischen Zustand anzeigen
python -m orchestrator approve --phase 04 --commit <sha> \
       --approver DEIN_NAME --decision APPROVE   # Human Gate (strict)
python -m orchestrator unblock       # BLOCKED -> READY
python -m orchestrator reset-phase   # Phase komplett neu starten
```

## Was liegt wo?

| Pfad | Inhalt |
|---|---|
| `src/`, `tests/` | das gebaute Programm (entsteht durch die Agenten) |
| `state/` | kanonischer Zustand + Journal (nicht anfassen) |
| `.orchestrator/artifacts/` | Prompts, Agent-Logs, Test-Evidence pro Lauf |
| `reports/` | Berichte; `human-gates/` + `acceptance/` sind agent-immutable |
| `ONE_SHOT_REPORT.md` | Abschluss-/Statusbericht jedes Laufs |
| `MASTER_ORCHESTRATOR.md` | normative Regeln (V4) |
| `docs/V4_CHANGES.md` | was V4 gegenüber dem V3-Plan geändert hat |

## Sicherheit (Kurzfassung)

Agenten dürfen nie: `state/`, `phases/`, `schemas/`, `prompts/`,
`orchestrator/`, Gate-/Test-Konfiguration ändern, committen, mergen oder
sich selbst freigeben. Das wird nach jedem Agent-Lauf per Git-Diff UND
Hash-Snapshot (für git-ignorierte Kontrolldateien) erzwungen; Verstöße
werden zurückgerollt und protokolliert, Wiederholung blockt die Phase.
