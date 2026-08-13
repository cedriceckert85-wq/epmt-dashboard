# Counsel — Claude & Codex entscheiden gemeinsam

`counsel` ist ein kleines CLI-Tool, das die **Claude Code CLI** und die **OpenAI Codex CLI**
in eine strukturierte Diskussion bringt: Beide KIs debattieren eine Software- oder
Design-Entscheidung über mehrere Runden, versuchen einen Konsens zu finden, und ein
Moderator fasst das Ergebnis als **Entscheidungsprotokoll (Decision Record)** zusammen.

## Voraussetzungen

- Node.js >= 18 (keine weiteren Abhängigkeiten)
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code` (eingeloggt via `claude login` bzw. `ANTHROPIC_API_KEY`)
- Codex CLI: `npm install -g @openai/codex` (eingeloggt via `codex login` bzw. `OPENAI_API_KEY`)

Beide CLIs werden **nicht-interaktiv** und **read-only** aufgerufen — der Counsel diskutiert
nur, er ändert keine Dateien.

## Schnellstart

```bash
node counsel/counsel.mjs "Sollen wir das Dashboard von Vanilla-JS auf React umstellen?"
```

Ablauf:

1. **Runde 1:** Claude eröffnet (Optionen + vorläufige Empfehlung), Codex antwortet (Zustimmung/Widerspruch).
2. **Weitere Runden:** Beide reagieren aufeinander; in der letzten Runde wird aktiv ein Konsens gesucht.
3. **Moderation:** Der Moderator (Default: Claude) schreibt das Entscheidungsprotokoll mit
   Entscheidung, Begründung, verworfenen Alternativen, Risiken, nächsten Schritten und Dissens.
4. Das komplette Protokoll inkl. Diskussionsverlauf landet in `counsel/sessions/<datum>-<thema>.md`.

## Beispiele

```bash
# 3 Runden, Codex eröffnet, Codex moderiert
node counsel/counsel.mjs --rounds 3 --first codex --moderator codex \
  "Wie strukturieren wir die Speku-Dashboard-Daten: eine grosse index.html oder Aufteilung?"

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
| `--rounds <n>` | Anzahl Diskussionsrunden (jede Runde = beide sprechen einmal) | `2` |
| `--first <claude\|codex>` | Wer die Diskussion eröffnet | `claude` |
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
