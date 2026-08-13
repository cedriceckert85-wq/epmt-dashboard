# Counsel — Setup-Anleitung für den Claude-Agenten

> **An den Claude-Agenten:** Diese Datei ist deine Arbeitsanweisung. Richte das
> Counsel-Tool (CLI + GUI) auf diesem Rechner ein. Arbeite die Schritte der Reihe
> nach ab, prüfe nach jedem Schritt das Ergebnis mit dem angegebenen Befehl, und
> melde dem Nutzer am Ende kurz, was funktioniert und was er noch selbst tun muss
> (insbesondere die Logins in Schritt 3 — die kannst du nicht für ihn erledigen).

## Was das ist

- `counsel/counsel.mjs` — Node-Skript ohne Abhängigkeiten. Lässt die Claude Code CLI
  und die OpenAI Codex CLI eine Software-/Design-Frage über mehrere Runden
  diskutieren (optional mehrköpfig: Rollen Design/Frontend/Backend, je einmal mit
  Claude und einmal mit Codex besetzt). Ein Moderator schreibt am Ende ein
  Entscheidungsprotokoll. Details: `counsel/README.md`.
- `counsel-gui/` — Rust/egui-Desktop-GUI: Mitlese-Feld (Diskussion live),
  Eingabefeld (Frage), Ergebnisfeld (Protokoll). Startet das Node-Skript als
  Kindprozess. Details: `counsel-gui/README.md`.

## Schritt 1: Entpacken und Grundlagen prüfen

Entpacke die ZIP an einen dauerhaften Ort (z. B. `~/counsel` bzw. `C:\Tools\counsel`)
und prüfe die Werkzeuge:

```bash
node --version    # brauchst du >= 18; sonst von https://nodejs.org installieren
cargo --version   # nur fuer die GUI noetig; sonst via https://rustup.rs installieren
```

Fehlt Node oder Rust: installiere es (Windows: winget `OpenJS.NodeJS.LTS` /
`Rustlang.Rustup`; macOS: `brew install node rustup`; Linux: Paketmanager oder
offizielle Installer). Frage den Nutzer, bevor du systemweit etwas installierst.

## Schritt 2: Die beiden KI-CLIs installieren

```bash
npm install -g @anthropic-ai/claude-code
npm install -g @openai/codex
claude --version
codex --version
```

## Schritt 3: Logins (muss der Nutzer selbst machen)

Beide CLIs brauchen ein eingeloggtes Konto. Fordere den Nutzer auf, in einem
Terminal auszuführen:

```bash
claude   # startet Claude Code; beim ersten Start Login im Browser durchlaufen
codex login
```

Alternativ funktionieren API-Keys über die Umgebungsvariablen `ANTHROPIC_API_KEY`
und `OPENAI_API_KEY`. Prüfen kannst du den Login so (beide Aufrufe müssen eine
Antwort liefern, nicht nach Login fragen):

```bash
echo "Antworte nur: OK" | claude -p --output-format text
echo "Antworte nur: OK" | codex exec --skip-git-repo-check -
```

## Schritt 4: Counsel-CLI testen

Im entpackten Verzeichnis:

```bash
# Ablauftest ohne API-Kosten (Stub-Antworten):
node counsel/counsel.mjs --dry-run "Testfrage"

# Echter Mini-Lauf (kostet API-Nutzung auf beiden Seiten, ~2-3 Minuten):
node counsel/counsel.mjs --rounds 1 "Kurzer Test: Tabs oder Spaces? Antworte knapp."
```

Erwartung: Die Diskussion läuft im Terminal durch, am Ende steht ein
Entscheidungsprotokoll und der Hinweis `Protokoll gespeichert: counsel/sessions/...`.

## Schritt 5: GUI bauen und starten

```bash
cd counsel-gui
cargo run --release
```

Der erste Build dauert einige Minuten. Unter **Linux** brauchst du ggf.
GUI-Bibliotheken (Debian/Ubuntu):

```bash
sudo apt install build-essential libxkbcommon-dev libwayland-dev \
  libxcb1-dev libgl1-mesa-dev
```

macOS und Windows brauchen nichts Zusätzliches (Windows: MSVC Build Tools müssen
für Rust vorhanden sein — richtet rustup normalerweise mit ein).

Erwartung: Ein Fenster „Counsel — Claude & Codex" öffnet sich. Frage unten
eintippen, Panel wählen (2 Architekten oder 6er-Panel Design/Frontend/Backend),
Start drücken, links mitlesen, rechts erscheint das Ergebnis.

**Wichtig:** Die GUI aus dem Repo-/Entpack-Root oder aus `counsel-gui/` starten,
damit sie `counsel/counsel.mjs` findet — oder den Pfad explizit setzen:
`COUNSEL_SCRIPT=/pfad/zu/counsel/counsel.mjs`.

## Troubleshooting

| Problem | Lösung |
|---|---|
| `claude`/`codex` nicht gefunden | npm-Global-Pfad nicht in PATH — `npm config get prefix` prüfen, dessen `bin` in PATH aufnehmen, Terminal neu starten |
| CLI fragt nach Login statt zu antworten | Schritt 3 wiederholen (Nutzer muss sich einloggen) |
| GUI-Build-Fehler unter Linux (`xkbcommon`, `wayland`, `GL`) | Pakete aus Schritt 5 installieren |
| GUI findet Skript nicht („counsel.mjs nicht gefunden") | Aus dem richtigen Verzeichnis starten oder `COUNSEL_SCRIPT` setzen |
| Codex-Aufruf schlägt in Firmennetzen fehl | Proxy-Umgebungsvariablen (`HTTPS_PROXY`) auch für die CLIs setzen |
| Lauf dauert sehr lange | Rundenzahl senken (`--rounds 1`) oder kleines Panel (2 Architekten) nutzen; Timeout pro Aufruf via `--timeout` erhöhen, falls Modelle lange denken |

## Abschlussmeldung an den Nutzer

Berichte am Ende kurz: ✅/❌ für Node, Rust, beide CLIs, beide Logins, Dry-Run,
GUI-Build — plus den Befehl, mit dem der Nutzer die GUI künftig startet.
