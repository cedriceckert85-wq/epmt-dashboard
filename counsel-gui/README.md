# Counsel GUI

Eine schlanke Desktop-Oberfläche (Rust + egui) für den [Counsel](../counsel/README.md):

- **Diskussion** (links): großes Mitlese-Feld — hier läuft die Debatte zwischen
  Claude und Codex live durch.
- **Ergebnis** (rechts): das fertige Entscheidungsprotokoll, mit Kopieren-Button.
- **Eingabe** (unten): ein Textfeld für deine Frage, Panel-Auswahl
  (2 Architekten oder Design + Frontend + Backend mit je Claude und Codex = 6 Köpfe),
  Rundenzahl, Start/Stopp. Enter startet.

Die GUI ist ein dünner Wrapper: sie startet `node counsel/counsel.mjs` als
Kindprozess und streamt dessen Ausgabe. Die ganze Diskussionslogik bleibt im
Skript — GUI und CLI verhalten sich identisch.

## Voraussetzungen

- Rust-Toolchain (`rustup`), Node.js sowie die eingeloggten CLIs `claude` und `codex`
  (siehe [counsel/README.md](../counsel/README.md))
- Linux: übliche GUI-Bibliotheken (X11/Wayland); auf macOS/Windows nichts weiter

## Bauen & Starten

```bash
cd counsel-gui
cargo run --release
```

Die GUI sucht `counsel/counsel.mjs` relativ zum Arbeitsverzeichnis (Repo-Root oder
`counsel-gui/`) bzw. neben der Binary. Liegt das Skript woanders:

```bash
COUNSEL_SCRIPT=/pfad/zu/counsel.mjs cargo run --release
```

## Bedienung

1. Frage unten eintippen, Panel und Runden wählen, **Start** (oder Enter).
2. Links mitlesen, während die Mitglieder nacheinander argumentieren.
3. Rechts erscheint am Ende das Entscheidungsprotokoll; das vollständige
   Protokoll liegt zusätzlich als Markdown in `counsel/sessions/`.
4. **Stopp** bricht einen laufenden Counsel ab.
