# Counsel — Claude & Codex entscheiden gemeinsam

`counsel` ist ein kleines CLI-Tool, das die **Claude Code CLI** und die **OpenAI Codex CLI**
in eine strukturierte Diskussion bringt: Die KIs debattieren eine Software- oder
Design-Entscheidung über mehrere Runden, versuchen einen Konsens zu finden, und ein
Moderator fasst das Ergebnis als **Entscheidungsprotokoll (Decision Record)** zusammen.

Der Counsel kann **mehrköpfig** besetzt werden: Jede Rolle (z. B. Design, Frontend,
Backend) wird doppelt besetzt — einmal mit Claude, einmal mit Codex. So diskutieren
bis zu sechs Perspektiven miteinander:

```
              ┌─ claude·design    ─┐
   Design  ───┤                    │
              └─ codex·design     ─┤
              ┌─ claude·frontend  ─┤
   Frontend ──┤                    ├──► Moderator ──► Entscheidungsprotokoll
              └─ codex·frontend   ─┤
              ┌─ claude·backend   ─┤
   Backend ───┤                    │
              └─ codex·backend    ─┘
```

## Voraussetzungen

- Node.js >= 18 (keine weiteren Abhängigkeiten)
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code` (eingeloggt via `claude login` bzw. `ANTHROPIC_API_KEY`)
- Codex CLI: `npm install -g @openai/codex` (eingeloggt via `codex login` bzw. `OPENAI_API_KEY`)

Beide CLIs werden **nicht-interaktiv** und **read-only** aufgerufen — der Counsel diskutiert
nur, er ändert keine Dateien.

## Schnellstart

```bash
# Klassisch: 2 Architekten (claude + codex)
node counsel/counsel.mjs "Sollen wir das Dashboard von Vanilla-JS auf React umstellen?"

# Mehrköpfig: Design-, Frontend- und Backend-Rolle, je mit Claude UND Codex besetzt (6 Mitglieder)
node counsel/counsel.mjs --roles design,frontend,backend "Wie bauen wir Feature X?"
```

Ablauf:

1. **Jede Runde:** Alle Mitglieder sprechen einmal, jeweils mit Blick auf den kompletten
   bisherigen Verlauf und aus der Perspektive ihrer Rolle. Das erste Mitglied eröffnet
   mit Optionen und einer vorläufigen Empfehlung, alle weiteren stimmen zu oder
   widersprechen begründet.
2. **Letzte Runde:** Alle versuchen aktiv, einen Konsens zu formulieren.
3. **Moderation:** Der Moderator (Default: Claude) schreibt das Entscheidungsprotokoll mit
   Entscheidung, Begründung, verworfenen Alternativen, Risiken, nächsten Schritten und
   Dissens (inkl. welche Rolle abweicht).
4. Das komplette Protokoll inkl. Diskussionsverlauf landet in `counsel/sessions/<datum>-<thema>.md`.

## Rollen

Eingebaut: `architekt` (Default), `design` (UI/UX), `frontend`, `backend`.
Eigene Rollen gehen über `--role-def`, eine freie Besetzung über `--member`:

```bash
# Eigene Rolle definieren und einzeln besetzen
node counsel/counsel.mjs \
  --role-def "security=Du bist Security-Engineer und bewertest Angriffsflaechen und Datenschutz." \
  --member claude:design --member codex:backend --member claude:security \
  "Duerfen wir die Kurs-Daten clientseitig cachen?"
```

## Beispiele

```bash
# Volles Panel, 2 Runden = 12 Wortmeldungen + Moderation
node counsel/counsel.mjs --roles design,frontend,backend --rounds 2 \
  "Wie strukturieren wir die Speku-Dashboard-Daten: eine grosse index.html oder Aufteilung?"

# 3 Runden, Codex spricht je Rolle zuerst, Codex moderiert
node counsel/counsel.mjs --rounds 3 --first codex --moderator codex "Frage..."

# Dateien als Kontext mitgeben
node counsel/counsel.mjs --context spec.html --context index.html \
  "Passt die aktuelle index.html noch zur Spezifikation?"

# Diskussion auf Englisch
node counsel/counsel.mjs --lang en "Monorepo vs. polyrepo for our tooling?"

# Ohne echte CLIs testen (Stub-Antworten, prüft nur den Ablauf)
node counsel/counsel.mjs --dry-run "Testfrage"
```

## Optionen

| Option | Bedeutung | Default |
|---|---|---|
| `--rounds <n>` | Anzahl Diskussionsrunden (jede Runde = alle sprechen einmal) | `2` |
| `--roles <liste>` | Rollen, je mit Claude und Codex besetzt (z. B. `design,frontend,backend`) | `architekt` |
| `--member <engine:rolle>` | Einzelnes Mitglied (mehrfach möglich, ersetzt `--roles`) | — |
| `--role-def <name=text>` | Eigene Rolle definieren (mehrfach möglich) | — |
| `--first <claude\|codex>` | Welche Engine je Rolle zuerst spricht | `claude` |
| `--moderator <claude\|codex>` | Wer das Entscheidungsprotokoll schreibt | `claude` |
| `--context <datei>` | Datei als Kontext in die Diskussion geben (mehrfach möglich) | — |
| `--lang <de\|en>` | Sprache der Diskussion | `de` |
| `--out <datei>` | Zielpfad für das Protokoll | `counsel/sessions/...` |
| `--model-claude <m>` | Modell für Claude (z. B. `claude-opus-5`) | CLI-Default |
| `--model-codex <m>` | Modell für Codex (z. B. `gpt-5-codex`) | CLI-Default |
| `--claude-cmd <cmd>` / `--codex-cmd <cmd>` | Abweichende CLI-Befehle | `claude` / `codex` |
| `--timeout <sek>` | Timeout pro CLI-Aufruf | `600` |
| `--dry-run` | Ablauf ohne echte CLIs testen | aus |

## Wie es technisch funktioniert

- **Claude** wird über `claude -p --output-format text` aufgerufen; der Prompt kommt über stdin,
  die Antwort über stdout.
- **Codex** wird über `codex exec --sandbox read-only --skip-git-repo-check -` aufgerufen; der
  Prompt kommt über stdin, die finale Agentennachricht wird sauber über
  `--output-last-message` ausgelesen.
- Jeder Teilnehmer bekommt bei jedem Zug den **kompletten bisherigen Diskussionsverlauf** plus
  eine Rollenbeschreibung („Du bist Teil eines zweiköpfigen Entscheidungsrats …") und eine
  Aufgabenanweisung (eröffnen / antworten / Konsens suchen).
- Die Diskussion läuft zustandslos über Prompts — es werden keine Sessions der CLIs
  wiederverwendet, dadurch bleibt alles reproduzierbar und im Protokoll nachvollziehbar.
