# PROMPT — Baue "LoL Clip Lab Local" (finale Fassung mit Counsel-Entscheidungen)

Kopiere ab hier alles in den Agenten:

---

## AUFBAU DIESES DOKUMENTS

Dieses Dokument hat drei Teile:

- **Teil A — Spezifikation:** WAS das Tool können muss (verbindlich, testbar).
- **Teil B — Architektur-Entscheidungen:** von einem Design-Counsel (drei
  Fachrollen, voller Konsens) getroffene Bauentscheidungen. **VERBINDLICH.**
- **Teil C — Die vier LLM-Prompts:** die fertigen Laufzeit-Prompts des Tools.
  **VERBINDLICH — wörtlich als versionierte Konstanten in `prompts.py`
  übernehmen** (nur die `{platzhalter}` werden zur Laufzeit ersetzt).

**Wichtig:** Teil B und C gehen der Anweisung „Entwirf die Architektur selbst"
in Teil A vor. Wo Teil B/C schweigen, entscheidest du weiterhin selbst und
dokumentierst es in DESIGN_NOTES.md.

---

# TEIL A — SPEZIFIKATION

## ROLLE UND MISSION

Du bist ein erfahrener Software-Engineer. Baue ein **komplett lokales
Kommandozeilen-Tool in Python**, das aus einer bereits heruntergeladenen
League-of-Legends-Stream-Aufnahme (VOD-Datei) ein **Edit-Sheet** erzeugt:
die besten Momente mit exakten Schnittpunkten, Kategorien, Stil- und
Kanal-Zuordnung, Caption/Zoom/SFX-Vorschlägen und YouTube-Kapitelmarkern.
Der kreative Kern ist ein LLM (lokale `claude`-CLI), das das komplette
Stream-Transkript liest und entscheidet, was clip-würdig ist und warum.

**WICHTIG: Entwirf die Architektur selbst.** Dieses Dokument definiert WAS
das Tool können muss (verbindlich, testbar) — WIE du es baust (Modulschnitt,
Algorithmen, Datenstrukturen), entscheidest du. Schaue dir keine bestehende
Implementierung an. Wo dieses Dokument eine Invariante nennt, ist sie
Pflicht; wo es schweigt, triff eine gute eigene Entscheidung und dokumentiere
sie kurz in einer DESIGN_NOTES.md.

## KONTEXT (Zielnutzer)

- Zwei deutschsprachige Streamer (Duo) mit DREI Kanälen:
  **insta** (vertikale Reels <60s, zwei Stile: funny-talk und montage),
  **yt** (geschnittene Highlight-Videos ~10 min),
  **uncut** (ganze Session, braucht nur Kapitelmarker).
- PC: Ryzen 7 5800X3D, **AMD Radeon RX 9070 XT**, 64 GB RAM, Windows.
  Ein Freund liefert OBS-Aufnahmen mit ZWEI Tonspuren (Spur 1 = Mix,
  Spur 2 = nur Mikrofon) und Beispiel-Clips als Stil-Referenzen.
- Kein Streaming, kein Upload, keine Cloud: NUR Analyse/Editing-Hilfe.

## HARTE REGELN (nicht verhandelbar)

1. **AMD-sicher:** Whisper läuft auf CPU (faster-whisper, int8). Encoding
   nutzt AMD AMF (`h264_amf`) wenn verfügbar, sonst CPU `libx264`.
   **NIEMALS NVENC, niemals CUDA** — auch nicht als Fallback-Zweig.
2. **Python 3.11+**, Abhängigkeiten NUR `numpy` und `faster-whisper`
   (lazy importiert). ffmpeg/ffprobe als externe Binaries — ffmpeg ist die
   EINZIGE harte Voraussetzung für echte VODs.
3. **Lokal:** Netz nur für pip-Install, den einmaligen Whisper-Modell-
   Download und die LLM-CLI-Aufrufe. Die Analyse selbst telefoniert nie.
4. **Graceful Degradation überall** (Matrix unten). Erwartbare Fehler
   erzeugen eine verständliche Meldung mit Lösungsweg, NIE einen Stacktrace.
5. Alles konfigurierbar über eine `config.toml` (tomllib), CLI-Flags
   überschreiben die Config. Kaputte Config → Warnung + Code-Defaults
   (niemals stilles Verschlucken).

## PIPELINE (fachlich, Reihenfolge frei optimierbar)

VOD → (ffmpeg) Audio mono 16kHz, wählbare Tonspur → (faster-whisper, CPU,
VAD, Wort-Timestamps) Transkript → (numpy) Reaktionserkennung auf dem Audio
→ optionale Game-Events aus JSON/CSV → Timeline-Dokument → LLM-Editorial
(zwei Pässe) → Ranking (Signal + Semantik) → Schnittplanung → Ausgaben.

## FUNKTIONALE ANFORDERUNGEN

### F1 — Ingest
- Container: alles was ffmpeg liest (mp4/mkv/webm/mov/avi/ts/m4v).
- Tonspur wählbar: CLI `--audio-stream a:1` UND Config-Key `audio_stream`
  (gilt auch für Batch). Default = ffmpeg-Standardspur.
- Dauer via ffprobe; WAV-Zwischendatei nach der Analyse löschen
  (Config-Schalter zum Behalten).

### F2 — Transkription
- faster-whisper CPU int8, Modellgröße konfigurierbar (tiny–medium),
  VAD an, Wort-Timestamps. Sprache auto-erkennen.
- Alternativ: `--transcript datei.json` überspringt Whisper komplett
  (Format: Segmente mit t0/t1/text, optional Wörter).
- Modell-Load/-Download-Fehler → klare Meldung („erster Lauf braucht einmal
  Internet; oder --transcript nutzen"), kein httpx-Stacktrace.

### F3 — Reaktionserkennung (pure numpy, deterministisch)
- Findet Stellen, wo die Streamer LAUT werden (Lachen/Schreien) über
  Kurzzeit-Energie relativ zur lokalen Baseline (robuste Statistik).
- Pflicht-Invarianten: leises/konstantes Audio (gemuteter Mic, Hum) darf
  KEINE Reaktionen erzeugen (absoluter Energie-Boden ~-50 dBFS UND Schutz
  gegen kollabierende Streuung); echte laute Ausbrüche (±20 dB über Baseline)
  werden mit Standard-Einstellungen auf ±2s gefunden; leerer Input crasht
  nicht; Intensität normiert 0..1; nahe Peaks werden gemerged.

### F4 — Game-Events (optional, Datei vom Nutzer)
- JSON (`{"events":[{"t":..,"kind":..,"weight":..}]}` oder Liste) und CSV
  (`t,kind[,weight]`, Header optional). Kaputte Zeilen überspringen;
  0 geparste Events aus vorhandener Datei → Warnung.
- Sinnvolle Default-Gewichte (penta hoch … death negativ), weight übersteuert.

### F5 — LLM-Editorial (der Kern!) — zwei Pässe über die `claude`-CLI
- LLM-Anbindung: Prompt via stdin an eine konfigurierbare CLI
  (`llm_cmd = ["claude","-p"]`); `{prompt}`-Platzhalter für Argument-CLIs;
  Executable via `shutil.which` zum vollen Pfad auflösen (Windows
  `.cmd`-Shims!); Timeout; Antwort = erstes balanciertes Top-Level-JSON
  (Objekt ODER Array) aus geschwätzigem Output extrahieren — Klammern in
  Strings/Escapes korrekt, begrenzte Versuche (kein O(n²) bei
  Klammer-Fluten), RecursionError abgefangen.
- **Session-Pass:** liest das GESAMTE Timeline-Dokument. Lange Sessions in
  zeilen-alignierten Chunks (~150k Zeichen, konfigurierbar), bisherige Funde
  werden in den nächsten Chunk mitgegeben und dedupliziert gemerged.
  NIEMALS einfach vorne abschneiden — ein Gag aus Minute 3 mit Payoff in
  Stunde 3 MUSS verbindbar sein. Ergebnis: running_gags, callbacks
  (setup_t/payoff_t), arcs, notes.
- **Moment-Pass:** bewertet Signal-Kandidaten UND darf eigene Momente ohne
  Game-Event entdecken. Log-Kontext: volle Details ±90s um jeden Kandidaten
  + gleichmäßige Stichprobe des Rests, Budget begrenzt, KEIN Kandidat darf
  seinen Kontext verlieren (auch nicht späte/sparse bei knappem Budget).
  Pro Moment liefert das LLM: t0/t1 (Schnittfenster inkl. Setup!),
  Kategorie, Score 0-10, punchline_t, Titel, Begründung, style-Tag,
  channels-Liste, callback_refs, lore_refs, captions[{t,text}],
  zooms[{t,duration}], sfx[{t,kind}].
- **Sanitisierung ist Pflicht:** JEDES LLM-Feld validieren — Tags nur aus
  bekannten Mengen, Strings begrenzt + Newlines kollabiert (landen in CSV,
  Dateinamen, Kapiteln!), Zahlen endlich geklemmt (json akzeptiert
  Infinity!), null-statt-Liste toleriert, Kategorie als pfadsicherer Slug.
- **Sprache:** Titel/Captions/Gag-Namen in der SPRACHE DER STREAMER
  (Prompt-Anweisung; per Config erzwingbar). **Hosts:** konfigurierbare
  Namensliste für korrekte Gag-Zuordnung im Duo.
- Momente-Matching auf Kandidaten über Zeit-Überlappung. Achtung Geometrie:
  Einzel-Event-Kandidaten sind punktförmig (t0==t1) — Punkt-in-Fenster
  zählt als Match; reine Kanten-Berührung zweier echter Fenster NICHT;
  identische Punktfenster sind Duplikate; Duplikat-Momente dürfen keine
  Ranking-Plätze verbrennen. Gematchte Kandidaten übernehmen das
  LLM-Schnittfenster.

### F6 — Kanal-Gedächtnis (persistentes „Gehirn")
- JSON-Datei sammelt über alle analysierten VODs: Running Gags MIT Zähler
  (times_seen, first/last_seen), Catchphrases, Lore, Session-Summaries
  (alles gecappt).
- VOR der Analyse als kompakter Block in beide LLM-Pässe injizieren →
  wiederkehrende Gags werden erkannt und Momente per lore_refs markiert.
- NACH der Analyse: LLM-Konsolidierung (bekannte Gags nach BEDEUTUNG
  hochzählen statt duplizieren) mit deterministischem mechanischem Fallback.
- Pflicht-Invarianten: **Re-Analyse derselben VOD (gleicher Name) erhöht
  KEINE Zähler** (nur Summary-Refresh); via lore_refs erkannte Gags zählen
  als Wiederauftreten; max. 1 Bump pro Gag pro Session; korrupte/feindliche
  Dateien (Infinity, Strings statt Dicts, tiefes Nesting) → frisches bzw.
  bereinigtes Gehirn, NIE Crash; Signal-only-Läufe verschmutzen das
  Gedächtnis nicht.
- CLI: anzeigen + löschen; `--no-memory` pro Lauf.

### F7 — Stil-Lernen aus Referenz-Clips
- Ordnerstruktur `references/<kanal>/<stil>/` (z. B. insta/funny,
  insta/montage) — zwei Ebenen; Ordnername→Stilname als sicherer Slug
  (`insta_funny`). Ebene 1 allein und Root-Videos funktionieren auch.
- Pro Clip Fingerprint: Dauer (ffprobe, nicht-endliche/negative Werte
  verwerfen), Schnitt-Tempo via ffmpeg-Szenenerkennung (Sample-Fenster),
  Transkript-Probe (geteiltes Whisper-Modell; ohne Whisper: ohne Text
  weiterlernen, nicht abbrechen).
- **Klassifikation ist Pflicht:** Referenzen mit Median-Dauer ≤ ~2 min
  = CUT-Stil (ideal-Cliplänge, Pace, Humor-Merkmale, Caption-Stil — per
  LLM destilliert, mechanischer Median-Fallback); längere = FORMAT-Profil
  (Ziel-LAUFZEIT des Kanals). **Ganze Videos dürfen NIE als
  Clip-Schnittstil enden** (kein erfundenes „ideal 90s" aus einem
  10-Minuten-Video). 0 cuts/min ist eine echte Messung („lange
  ungeschnittene Takes").
- Nur CUT-Stile werden dem Moment-Pass zum Taggen angeboten (jeder
  Stilname muss den Prompt erreichen, Budget fair aufteilen); FORMAT-
  Profile speisen die Kanal-Pläne (Ziel-Laufzeit).
- Kohärenz-Regel: Stil `<kanal>_<x>` impliziert diesen Kanal automatisch.
- CLI: `learn [ordner]` (legt beim ersten Mal die Beispielstruktur an,
  druckt pro Stil das Gelernte), `--no-llm`-Variante; Profil-Datei
  versioniert, korruptes Laden → leer, alles sanitisiert.

### F8 — Kanal-Routing und Pläne
- Kanäle in config.toml als Liste: name, note (Prompt-Hinweis), optional
  `kind="full"` (Ganz-VOD-Kanal), `max_s` (Warnschwelle), `vertical=true`.
  Defaults: insta(max 60s, vertical), yt, uncut(full). Beliebig umbenennbar
  — alles folgt den Config-Namen; kaputte Einträge tolerieren + warnen.
- LLM taggt jeden Moment mit allen passenden Kanälen (validiert).
- Edit-Sheet endet mit Kanal-Plänen: Clip-Kanäle **CHRONOLOGISCH mit
  Timecodes** (Story-Reihenfolge fürs Video; Rang pro Zeile), Längenwarnung
  über max_s, gelernte Format-Laufzeit anzeigen; kind=full zeigt auf
  chapters.txt statt einer Clip-Liste.
- **chapters.txt** bei jeder Analyse: YouTube-tauglich — erstes Kapitel
  EXAKT `00:00` (früher erster Clip wird selbst der Opener), aufsteigend,
  ≥10s Abstand (nähere falten ins vorherige), `H:MM:SS`/`MM:SS`.

### F9 — Doppel-Gehirn (Zweitmeinung)
- Optionale zweite CLI (Default-Beispiel: `codex exec -`), erhält den
  IDENTISCHEN Moment-Prompt. Blend: von beiden bewertete Clips → Score-
  Mittelwert + Notiz; vom Primär übersprungene → Zweitmeinung übernehmen;
  neue Fenster → aufnehmen (aber nicht mit eigenen Funden matchen und
  keine Duplikate erzeugen). Die Arbeit des Primär-Gehirns (Titel,
  Captions) darf NIE überschrieben werden, auch bei Score 0. Nicht
  installiert → still überspringen; Müll-Antwort → Primär-Ergebnis
  unangetastet. Session-Pass + Gedächtnis bleiben Primär-only.

### F10 — Ranking
- final = w_signal·norm(signal) + w_semantic·norm(semantic) (Default
  0.45/0.55), deterministisch, stabiler Tiebreak. Divisionen gegen
  Null-Summen abgesichert.
- Per-10-Minuten-Cap gegen Crowding; globales top_k skaliert mit der
  Session-Dauer (4h-Stream ≠ 12 Clips).

### F11 — Schnittplanung (EDL)
- Punchline-bewusst: Ende kurz nach punchline_t (konfigurierbarer Decay);
  Kategorie-abhängiger Setup-Vorlauf — ABER NICHT zusätzlich, wenn das
  Fenster schon vom LLM kommt (das enthält sein Setup bereits).
- Längen: min/max aus Config; die Ziel-Länge eines gelernten CUT-Stils darf
  das generische Maximum übersteuern (mit Obergrenze ~90s).
- Media-Grenzen: Fenster fester Länge in [0, Dauer] SCHIEBEN statt Kanten
  zu klemmen — Mindestlänge gilt auch am VOD-Anfang/-Ende (Penta in den
  letzten Sekunden!); VOD kürzer als Minimum → ganze VOD.
- Überlappende Clips mergen (besserer gewinnt), Ränge neu nummerieren;
  Overlays (captions/zooms/sfx) in den Clip geklemmt; callback_refs nur
  auf früheres Material.

### F12 — Ausgaben (pro VOD, Ordner neben der VOD)
- `edit_sheet.md` (Mensch): Header mit Stats (+Gedächtnis-Stand), pro Clip:
  Rang, Emoji-Kategorie, Titel, Score, Cut-Timecodes+Dauer, `Cut as: <stil>`,
  `Channels: …`, Punchline-Zeile (ehrlich: „ends just after" vs „runs on"),
  Warum, Transkript-Auszug (Kopf UND Ende — die Pointe darf nicht dem
  Truncating zum Opfer fallen), Captions/Zooms/SFX, Callback-Inserts,
  🧠-Lore-Zeilen; danach die Kanal-Pläne.
- `edit_plan.json` (Maschine, komplette Felder), `clips.csv`
  (parsebar! Titel gequotet, Stil/Kanäle kommasicher), `chapters.txt`.

### F13 — CLI (`python -m <paket>`)
`analyze VOD [--out] [--transcript] [--events] [--audio-stream] [--whisper-model]
[--no-llm] [--no-memory] [--no-style] [--cut] [--encoder]` ·
`batch ORDNER [dieselben Flags] [--audio-stream]` (pro Datei weiter bei
Fehlern, Sammel-Exit) · `cut VOD PLAN.json [--out]` (validiert Plan-Datei
und -Form; erkennt ffmpegs Stumm-Fehlschlag: Range außerhalb des Videos →
Fehler statt leerer Datei, abgeschnittene Ranges → ehrliche Notiz;
Kanal-Namen im Dateinamen; vertical-Kanäle → 9:16-Crop) · `learn` ·
`fetch URL... [--style kanal/stil]` (yt-dlp, `--`-Trenner gegen Options-
Injection, %-Escaping, Slug gegen Pfad-Traversal, Rechte-Hinweis) ·
`memory [--clear]` · `doctor` (zeigt ehrlich was da ist, ffmpeg als
einzig Fatales, Hinweis auf einmaligen Modell-Download) · `selftest`.
- Alle Fehlerpfade freundlich: fehlende Dateien → Exit 2 + Meldung;
  operative Fehler zentral abgefangen → Exit 1 + Meldung.

### F14 — Bootstrap und Launcher
- `bootstrap.py`: venv anlegen, deps installieren, doctor, selftest —
  ein Befehl, idempotent, klare Ausgaben.
- `START.bat` (Windows): Doppelklick = Setup+Selbsttest; DATEI draufziehen
  = analyze; ORDNER draufziehen = batch. **cmd-Parser-Fallen:** keine
  nackten Klammern in echo innerhalb von if-Blöcken; KEIN
  enabledelayedexpansion (frisst `!` in Dateinamen); %~1 überall gequotet.
- `start.sh` analog für Linux/Mac.

### F15 — Selftest (Beweis ohne Abhängigkeiten)
- Mitgelieferte Fixtures (Beispiel-Session MIT Running Gag der sich
  auflöst + Events) + **kanned Demo-LLM** (deterministisch, kein Netz,
  kein ffmpeg/whisper nötig): führt den kompletten Kreativ-Pfad vor —
  inkl. ZWEI Sessions gegen ein Scratch-Gedächtnis (zweiter Lauf erkennt
  die Gags: Zähler 2x, 🧠-Zeilen), Stil-Demo (`Cut as:`), Kanal-Pläne,
  chapters.txt. Pflicht: byte-deterministisch, berührt NIE das echte
  Gedächtnis/Profil, spawnt NIE echte CLIs (auch wenn codex/claude auf
  dem PATH sind), unabhängig von Nutzer-Umbenennungen in config.toml.

## DEGRADATIONS-MATRIX (Pflichtverhalten)

| fehlt | Verhalten |
|---|---|
| LLM-CLI | Signal-only-Ranking, brauchbares Sheet, klar gekennzeichnet |
| Zweit-CLI | still überspringen |
| faster-whisper / Modell | klare Meldung + `--transcript`-Ausweg |
| ffmpeg | einziger Fatal für echte VODs (doctor sagt es) |
| Events-Datei | läuft ohne |
| Referenzen/Stile | läuft ohne Stil-Tagging |
| Gedächtnis-Datei korrupt | frisches/bereinigtes Gehirn |
| config.toml kaputt | Warnung + Defaults |

## TESTS UND ABNAHME (Definition of Done)

1. **Unit-/Integrationstests mit pytest** für JEDE Anforderung oben —
   Ziel-Größenordnung 200+; reine Logik ohne echte Binaries testbar
   (IO injizierbar), feindliche LLM-Antworten als eigene Testklasse
   (Infinity, null-Listen, Nicht-Strings, Klammer-Fluten, tiefes
   Nesting, Kommas/Pfad-Zeichen in freiem Text).
2. `python -m <paket> selftest` läuft frisch entpackt ohne alles durch.
3. Wenn ffmpeg verfügbar: synthetisches Testvideo generieren und
   ingest/reactions/cut real beweisen (2-Spuren-Fall inkl. a:1).
4. Am Ende lieferst du: die ZIP (Quellcode+Tests+Fixtures+README mit
   deutscher Kurzanleitung), DESIGN_NOTES.md (deine Architektur-
   Entscheidungen + bewusste Abweichungen), Testreport, und das
   edit_sheet.md deines Selftests als Arbeitsprobe.

## WAS NICHT REIN SOLL

Kein Streaming/OBS-Steuerung, kein Upload/Publishing, keine Riot-Live-API,
kein GUI, keine Datenbank, kein Docker, keine GPU-Transkription, keine
zusätzlichen pip-Abhängigkeiten. Scope ist NUR: VOD rein → Edit-Sheet raus.

---

# TEIL B — ARCHITEKTUR-ENTSCHEIDUNGEN (verbindlich)

## B1 — Modulschnitt (Pipeline-orientiert, 12 Module)

Paketstruktur nach Pipeline-Stufen, NICHT nach Schichten:
`ingest.py`, `transcribe.py`, `reactions.py`, `events.py`, `timeline.py`,
`llm/{client,extract,merge,chunk,sanitize,prompts}.py`, `memory.py`,
`style.py`, `rank.py`, `edl.py`, `outputs.py`, `cli.py` + `pipeline.py`
(Orchestrator). Jede Stufe: reine Funktionen, IO (ffmpeg, Subprocess,
Dateisystem) nur an den Rändern und injizierbar.

## B2 — Zentrales Datenmodell

Ein abhängigkeitsfreies `model.py` als einzige gemeinsame Wahrheit: frozen
dataclasses `TimelineDoc`, `Candidate`, `Moment`, `MemoryState`,
`StyleProfile` — plus die Config als **validierter dataclass-Typ** (kein
loses dict; „kaputte Config → Defaults" wird EINMAL beim Parsen gelöst).

## B3 — Import-Regel (zyklenfrei, von Anfang an erzwungen)

`model.py` importiert nichts aus dem Paket. Fachmodule importieren NUR
`model.py`, nie einander. Kopplung ausschließlich über `pipeline.py`/`cli.py`.
Diese Regel als einfachen Importgraph-Test von Anfang an mitlaufen lassen.

## B4 — LLM-Anbindung als Systemgrenze

- `llm/client.py`: Subprocess-Spawn, Timeout, Executable-Auflösung — weiß
  NICHTS über Inhalte (reine Bytes rein/raus). Ein gemeinsames
  `resolve_executable()` (shutil.which, Windows-`.cmd`-Shims), das auch
  `doctor` und `cli.py` benutzen — sonst diagnostiziert doctor etwas
  anderes, als der echte Lauf trifft.
- `llm/extract.py`: balancierter Top-Level-JSON-Scan als **iterativer
  Stack-Scanner** (kein rekursiver Abstieg) mit Zeichen-Budget und
  Klammertiefen-Deckel; RecursionError TROTZDEM defensiv abfangen
  (Spec-Invariante bleibt zusätzlich abgesichert).
- `llm/sanitize.py`: EIGENES Modul, wird direkt am Extractor-Ausgang
  angewendet — dokumentierte Pipeline-Invariante. Zahlen-Klemmung
  (Infinity/NaN) passiert VOR jeder Vergleichs-/Sortierlogik, damit kein
  Infinity-Score das Ranking kontaminiert.
- `llm/merge.py`: Chunk-übergreifendes Mergen von Session-Pass-Funden über
  normalisierten Namens-Key (lowercase, whitespace-collapsed), nicht über
  exakten String-Match.
- `llm/chunk.py`: zeichenbasiertes Session-Pass-Chunking. Das ZEITbasierte
  Kandidaten-Kontextfenster (±90s + Stichprobe) gehört dagegen zu
  `timeline.py` — zwei verschiedene Fenster-Konzepte, nicht verschmelzen.
- `llm/prompts.py`: die Prompts aus Teil C als **versionierte Konstanten**,
  keine verstreuten f-Strings (der byte-deterministische Selftest hängt am
  exakten Wortlaut).
- `LLMClient`-Protocol (Protocol/ABC), damit Demo-LLM (Selftest) und echte
  CLI hinter derselben Schnittstelle austauschbar sind.

## B5 — Persistenz (Gedächtnis & Stil-Profile)

Strikt Read-Validate-Merge-Write-atomic: permissiver Reader (Unbekanntes/
Falschgetyptes verwerfen, nie werfen), Schreiben via Temp-Datei +
`os.replace`. ZWEI getrennte Dedup-Funktionen in `memory.py`:
`merge_gags_by_name()` (Chunk-Merge-Konsolidierung) und
`should_bump_counter(vod_id, session_seen)` (Re-Analyse-Schutz mit stabilem
VOD-Identitätsschlüssel im Datenmodell). Beide zu verschmelzen wäre genau
der Bug, der „max. 1 Bump pro Gag pro Session" bricht.

## B6 — Zweit-Gehirn (F9)

Blend ist reines Post-Processing: darf NICHT in `memory.py`/`rank.py`
schreiben, bevor der Blend abgeschlossen oder per Timeout beendet ist.
Fehlschlag der Zweit-CLI wird auf Subprocess-Ebene abgefangen, nie auf
Pipeline-Ebene. Die Zweit-CLI läuft durch denselben Extract/Sanitize-Pfad;
Blend erst NACH Sanitize beider Seiten.

## B7 — Teststrategie

Parametrisierte Tabellen-Tests (viele kleine Fälle) statt 200
Einzelfunktionen. Die Pflicht-Testklasse „feindliche LLM-Antworten"
(Infinity, null-Listen, Nicht-Strings, Klammer-Fluten, tiefes Nesting,
Kommas/Pfadzeichen) läuft komplett ohne Subprozesse gegen
`sanitize.py`/`extract.py`. Reale Subprozesse nur in optionalen
ffmpeg-Integrationstests.

## B8 — Baureihenfolge

1. `model.py` (Datenmodell + Config-Typ) — abhängigkeitsfreie Grundlage.
2. `llm/`-Untermodule mit `LLMClient`-Protocol; iterativer Extractor zuerst
   (entsperrt die Fuzz-Tests).
3. `memory.py` mit atomarer Persistenz und den zwei Dedup-Funktionen.
4. Importgraph-Test aufsetzen (Regel B3), dann restliche Pipeline-Stufen.
5. `resolve_executable()` in `client.py`, wiederverwendet von doctor/cli.
6. Feindliche-Antworten-Testklasse gegen `sanitize.py`/`extract.py`.
7. Selftest-Pfad (kanned Demo-LLM, zwei Sessions gegen Scratch-Gedächtnis)
   früh aufsetzen und Determinismus fortlaufend verifizieren.

---

# TEIL C — DIE VIER LLM-PROMPTS (verbindlich, woertlich in prompts.py)

Alle vier Prompts folgen dem im Counsel abgestimmten Grundgerüst: **Rolle → Hosts/Sprache → Gedächtnis → (Kategorie-Definitionen, nur Moment-Pass) → Daten → Schema mit Format-Kommentaren → Kürze-Priorität → „Nur JSON"-Schlusssatz.** Platzhalter in `{geschweiften_klammern}` werden zur Laufzeit ersetzt.

---

## 1) Session-Pass

```
Du bist Editorial-Analyst für einen deutschsprachigen League-of-Legends-Stream.
Du liest ein Timeline-Transkript und findest wiederkehrende Gags, Callbacks
(Setup + späterer Payoff), Handlungsbögen (Arcs) und sonstige Notizen für
spätere Clip-Auswahl. Du triffst hier KEINE Clip-Entscheidungen — nur
Struktur-Erkennung im Gesamtverlauf.

HOSTS: {host_namen}
Ordne Gags/Callbacks dem richtigen Host zu, wenn erkennbar (z. B. im
"description"-Feld erwähnen wer den Gag trägt). Rate nicht bei Unsicherheit.

SPRACHE: Titel, Namen und Beschreibungen in der Sprache der Streamer im
Transkript. {sprache_erzwungen_hinweis}

BEKANNTES GEDÄCHTNIS (aus früheren Sessions, kompakt):
{memory_block}
Wiedererkannte Gags aus dem Gedächtnis: verwende deren "id" weiter, lege
KEINE neue an. Ein Gag, der hier auftaucht, aber im Gedächtnis fehlt, ist neu.

Du erhältst Chunk {chunk_index}/{chunk_total} eines langen Transkripts.
Die Liste "bisherige_funde" enthält Gags/Callbacks/Arcs aus früheren Chunks
DIESER Session:
{bisherige_funde}

REGELN FÜR DIE AKTUALISIERUNG (verbindlich):
- Gib die VOLLSTÄNDIGE, aktualisierte Liste zurück — keine Deltas. Bereits
  bekannte Einträge fortschreiben (z. B. payoff_t ergänzen), neue anhängen.
- Wenn ein Eintrag aus "bisherige_funde" zum selben Gag/Callback/Arc gehört,
  den du gerade aktualisierst, VERWENDE DESSEN id UNVERÄNDERT weiter. Vergib
  eine neue id nur für tatsächlich neue Gags/Callbacks/Arcs.
- Einträge aus "bisherige_funde", die im aktuellen Chunk NICHT erwähnt
  werden, bleiben UNVERÄNDERT in der Ausgabe — nicht löschen, nicht
  vermuten dass sie beendet sind. Ein Gag, der einen Chunk pausiert, ist
  kein beendeter Gag.
- Max. {max_running_gags} running_gags — wichtigste zuerst, wenn mehr
  gefunden werden fasse ähnliche zusammen statt zu kappen.
- Ein Callback braucht ZWEI unterschiedliche Zeitpunkte: setup_t (wo der
  Gag zuerst etabliert wird) und payoff_t (wo er wieder aufgegriffen wird).
  Wenn du einen Payoff erkennst, suche im BISHERIGEN Transkript (auch aus
  früheren Chunks, über "bisherige_funde" oder deine eigene Erinnerung an
  vorige Chunks) nach dem Setup zurück. Rate NICHT — wenn du kein
  belastbares Setup findest, gehört der Fund in "notes", nicht in
  "callbacks".

TRANSKRIPT-CHUNK:
{timeline_chunk}

AUFGABE: Extrahiere/aktualisiere running_gags, callbacks, arcs, notes für
diesen gesamten Kontext (bisherige Funde + aktueller Chunk).

AUSGABESCHEMA (exakt, sonst nichts):
{
  "running_gags": [
    {
      "id": "string, stabiler slug, z.B. \"stolper_gag\"",
      "name": "kurzer Spitzname (2-4 Wörter), wie die Streamer den Gag selbst nennen würden oder nennen sollten — KEINE Beschreibung des Ereignisses",
      "first_t": 0.0,
      "description": "1 Satz, Details des Gags"
    }
  ],
  "callbacks": [
    {
      "setup_t": 0.0,
      "payoff_t": 0.0,
      "description": "1 Satz, was Setup und Payoff verbindet"
    }
  ],
  "arcs": [
    {
      "name": "kurzer Name",
      "start_t": 0.0,
      "end_t": 0.0,
      "description": "1 Satz"
    }
  ],
  "notes": ["freie Stichpunkte zu Beobachtungen ohne festen Platz oben, z.B. vermutete aber unbestätigte Callbacks"]
}

// alle Zeit-Felder (first_t, setup_t, payoff_t, start_t, end_t): Sekunden
// als Zahl (float), relativ zum VOD-Start, NIE "MM:SS"-Strings.
// Leere Kategorien als [] zurückgeben, NIE null.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- Wird einmal pro Chunk aufgerufen (~150k Zeichen, konfigurierbar, zeilen-aligniert), bei Chunk 1 ist `bisherige_funde` eine leere Struktur (`{"running_gags":[],"callbacks":[],"arcs":[],"notes":[]}`), NIEMALS `null` oder weggelassen.
- `memory_block` kommt aus F6 (Kanal-Gedächtnis) und bleibt über alle Chunks derselben Session identisch — nicht pro Chunk neu befüllen.
- Sanitizer muss: `id` als pfadsicheren Slug erzwingen (auch wenn das Modell Leerzeichen/Sonderzeichen liefert), Dedup nach `id` bei identischen Objekten aus konsekutiven Chunk-Antworten, Zeit-Felder auf endliche Zahlen klemmen, `notes` auf String-Liste beschränkt (keine Objekte).

---

## 2) Moment-Pass

```
Du bist Editorial-Analyst für einen deutschsprachigen League-of-Legends-Stream
mit drei Kanälen. Du bewertest Kandidaten-Momente für Kurz-Clips UND darfst
eigene Momente entdecken, die keinen Game-Event-Kandidaten haben.

HOSTS: {host_namen}
Ordne Gags/Pointen dem richtigen Host zu, wo erkennbar.

SPRACHE: title, reasoning und Caption-Texte in der Sprache der Streamer.
{sprache_erzwungen_hinweis}

BEKANNTES GEDÄCHTNIS (Running Gags/Catchphrases/Lore aus früheren Sessions):
{memory_block}
Erkennst du einen Moment als Fortsetzung eines bekannten Gags, trage dessen
id in "lore_refs" ein. Wenn du unsicher bist, ob eine ID passt, LASS DEN
VERWEIS WEG statt zu raten. Ein fehlender Lore-Verweis kostet uns eine Zeile
im Sheet. Ein erfundener Verweis kostet uns das Vertrauen der Editoren in
ALLE Lore-Verweise.

KATEGORIEN (wähle die naheliegendste, nicht die extremste):
- "punchline": pointierter Wortwitz mit klarem Vorher/Nachher
- "chaos": eskalierende Situation ohne einzelne Pointe
- "outplay": Skill-Moment, Reaktion ist Bewunderung nicht Lachen
- "callback": Gag-Wiederaufnahme — erfordert MINDESTENS einen Eintrag in
  callback_refs. Ohne callback_refs wähle eine andere Kategorie.

STYLE-TAGS — "style" MUSS einer dieser Werte sein, sonst leerer String "":
{stil_liste}

KANÄLE — "channels" MUSS eine Teilmenge dieser Namen sein:
{kanal_liste}

KANDIDATEN mit vollem Log-Kontext (±90s um den jeweiligen Zeitpunkt):
{kandidaten}

STICHPROBE des restlichen Transkripts (für eigene Funde ohne Game-Event):
{stichprobe}
Eigene Funde in der Stichprobe unterliegen denselben Kategorie- und
Score-Maßstäben wie die Kandidaten. Auffälliges Transkript (Großschreibung,
Ausrufezeichen, Länge) ist KEIN Signal für Clip-Würdigkeit — bewerte den
Inhalt, nicht die Textoberfläche.

SCHNITTFENSTER (t0/t1):
t0 = frühester Punkt, an dem ein Zuschauer OHNE Vorwissen die Pointe
versteht — nicht der früheste Punkt, an dem das Thema beginnt. Wenn Setup
und Pointe mehr als ~20s auseinanderliegen, prüfe ob ein kürzeres t0
möglich ist, das trotzdem verständlich bleibt.
punchline_t MUSS im Intervall [t0, t1] liegen. Wenn die eigentliche Pointe
außerhalb deines gewählten Fensters liegt, korrigiere t0/t1 statt
punchline_t zu verschieben.

CAPTIONS/ZOOMS/SFX: sparsam setzen, primär auf punchline_t, max. 1-2
zusätzliche auf klare Sekundärmomente. Kein Overlay-Teppich über den
ganzen Clip.

AUSGABESCHEMA (exakt, sonst nichts):
{
  "moments": [
    {
      "t0": 0.0,
      "t1": 0.0,
      "category": "punchline | chaos | outplay | callback",
      "score": 0,
      "punchline_t": 0.0,
      "title": "max. 8 Wörter, ein Satz, keine Zeilenumbrüche/Anführungszeichen",
      "reasoning": "max. 30 Wörter, Struktur: \"<Warum clip-würdig>. <Bezug falls callback/lore>.\" Kein Fließtext-Fazit.",
      "style": "einer aus stil_liste oder \"\"",
      "channels": ["teilmenge von kanal_liste"],
      "callback_refs": ["gag_id, nur bekannte IDs"],
      "lore_refs": ["gag_id, nur bekannte IDs"],
      "captions": [{"t": 0.0, "text": "kurz, ein Satz"}],
      "zooms": [{"t": 0.0, "duration": 0.0}],
      "sfx": [{"t": 0.0, "kind": "kurzes Schlagwort, z.B. \"airhorn\""}]
    }
  ]
}

// alle Zeit-Felder (t0, t1, punchline_t, captions[].t, zooms[].t, sfx[].t):
// Sekunden als Zahl (float), relativ zum VOD-Start, NIE "MM:SS"-Strings.
// score: ganze Zahl 0-10.
// Leere Arrays (callback_refs, lore_refs, captions, zooms, sfx) als [],
// NIE null.

PRIORITÄT BEI KNAPPEM PLATZ: Gib ALLEN Kandidaten ein vollständiges,
valides JSON-Objekt zurück. Ein vollständiges JSON mit knappen Feldern hat
IMMER Priorität vor ausführlichen Feldern. Wenn du bei vielen Kandidaten
Platz sparen musst, kürze zuerst Freitext-Felder (title, reasoning,
Caption-Texte) — NIE Timecodes, NIE Pflichtfelder, NIE die Anzahl der
zurückgegebenen Kandidaten.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- `kandidaten` enthält für jeden Signal-Kandidaten den vollen Transkript-Kontext ±90s; `stichprobe` ist die gleichmäßige Restsample-Auswahl innerhalb des Token-Budgets — kein Kandidat darf seinen ±90s-Kontext verlieren, auch nicht späte/sparse bei knappem Budget (das ist Aufrufer-Logik, nicht Prompt-Logik, aber die Reihenfolge im Prompt sollte Kandidaten vor Stichprobe halten, damit Truncation zuerst die Stichprobe kappt).
- Sanitizer MUSS trotz Prompt-Bitte hart durchsetzen: `punchline_t = clamp(punchline_t, t0, t1)`, `style`/`channels` gegen die bekannten Mengen filtern (nicht nur warnen), `callback_refs`/`lore_refs` gegen bekannte IDs filtern, `category=="callback"` ohne `callback_refs` auf nächstpassende Kategorie umbiegen oder Score-Penalty statt Crash.
- Bei Zweitmeinung (F9) wird dieser Prompt identisch an die zweite CLI geschickt — `memory_block`/`stil_liste`/`kanal_liste` müssen exakt dieselben Werte wie beim Primär-Aufruf sein, sonst sind die Bewertungen nicht vergleichbar.

---

## 3) Gedächtnis-Konsolidierung

```
Du pflegst das Langzeit-Gedächtnis eines League-of-Legends-Streamer-Duos.
Du entscheidest NICHT über neue Inhalte — du ordnest nur zu, welche in
dieser Session erkannten Gags bereits bekannte Gags aus dem Gedächtnis
sind (dann hochzählen) und welche mehrfach benannten Einträge derselben
Session eigentlich derselbe Gag sind (dann zusammenführen).

BEKANNTE GAGS AUS DEM GEDÄCHTNIS (id, name, description, times_seen):
{known_gags}

IN DIESER SESSION ALS LORE ERKANNTE VERWEISE (aus dem Moment-Pass,
lore_refs, sowie Session-Pass running_gags dieser Session):
{new_lore_hits}

AUFGABE:
- "bumped": Liste der ids aus known_gags, die in dieser Session
  nachweislich wieder aufgetreten sind (via lore_refs oder erneut
  erkanntem running_gag). Jede id MAX. EINMAL in der Liste, auch wenn sie
  mehrfach in der Session auftrat — ein Bump pro Gag pro Session.
- "merged": Fälle, in denen zwei oder mehr ids (aus known_gags oder neu in
  dieser Session vergebene ids) denselben Gag beschreiben. "into" = die id,
  die bestehen bleibt (bevorzugt die ältere/bekanntere aus known_gags),
  "from" = die id(s), die darin aufgehen.

Erfinde KEINE neuen Gags und ändere KEINE Namen/Beschreibungen — das ist
nicht deine Aufgabe hier. Wenn du unsicher bist, ob zwei Gags identisch
sind, NICHT mergen — lieber getrennt lassen als fälschlich zusammenlegen.

AUSGABESCHEMA (exakt, sonst nichts):
{
  "bumped": ["gag_id", "..."],
  "merged": [
    {"into": "gag_id", "from": ["gag_id2", "gag_id3"]}
  ]
}

// Nur IDs, keine vollständigen Gag-Objekte. Leere Arrays als [], NIE null.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- Wird EINMAL nach Abschluss beider LLM-Pässe pro Session aufgerufen, ausschließlich mit dem Primär-Gehirn (F9: Zweit-CLI bleibt hier außen vor).
- Deterministischer mechanischer Fallback (bei fehlender LLM-CLI oder Müll-Antwort) muss exakt dasselbe Ausgabeformat erzeugen: reines ID-Matching zwischen `lore_refs`/erkannten `running_gags`-ids und `known_gags`-ids für `bumped`, kein `merged` (Merge-Erkennung ohne LLM ist zu unsicher, leer lassen).
- Re-Analyse derselben VOD darf laut Spezifikation KEINE Zähler erhöhen — das muss VOR diesem Prompt-Aufruf geprüft werden (VOD-Name gegen bereits verarbeitete Sessions im Gedächtnis), nicht im Prompt selbst, da das Modell diese Prüfung nicht zuverlässig leisten kann.

---

## 4) Stil-Destillation

```
Du analysierst Referenz-Clips, um daraus einen wiederverwendbaren
Schnitt-Stil für kurze Highlight-Clips (CUT-Stil) zu destillieren. Du
bekommst pro Stil mehrere Fingerprints (technische Messwerte + kurze
Transkript-Proben) echter Beispiel-Clips desselben Stils.

Destilliere NUR die CUT-Stile, die dir unten mit Fingerprint-Daten
übergeben werden — erfinde keine Werte für Formate ohne Daten und
erfinde keine zusätzlichen Stile, die nicht in der Eingabe vorkommen.

FINGERPRINTS (pro Stil: Liste von {duration_s, cuts_per_min,
transcript_sample}):
{fingerprints}

Für jeden Stil destilliere:
- ideal_clip_s: typische/mediane Ziellänge in Sekunden für diesen Stil,
  basierend auf den gemessenen duration_s-Werten — kein erfundener Wert,
  wenn die Messungen stark streuen nimm den Median und sag das implizit
  über eine engere/weitere Einschätzung in pace nicht in der Zahl.
- pace: kurze Einschätzung des Schnitt-Tempos (z.B. "schnell, viele kurze
  Cuts" oder "wenige lange Einstellungen") basierend auf cuts_per_min.
  0 cuts/min ist eine valide Messung ("lange ungeschnittene Takes") —
  behandle sie nicht als fehlende Daten.
- humor_notes: 3-5 kurze, semikolon-getrennte Stichpunkte zu konkreten
  wiederkehrenden Mustern (Wortspiel-Dichte, Ton-Wechsel, Break-Charakter),
  KEINE Stilkritik, KEIN Fließtext-Absatz.
- caption_style: kurze Einschätzung, wie/ob Text auf dem Bild eingesetzt
  wird, basierend auf den Transkript-Proben (falls erkennbar), sonst "".

AUSGABESCHEMA (exakt, sonst nichts):
{
  "styles": {
    "<style_name>": {
      "ideal_clip_s": 0.0,
      "pace": "kurzer Satz",
      "humor_notes": "3-5 Stichpunkte, semikolon-getrennt",
      "caption_style": "kurzer Satz oder leer"
    }
  }
}

// style_name-Schlüssel MÜSSEN exakt den Stilnamen aus den Fingerprints
// übernehmen (z.B. "insta_funny"), keine Umbenennung/Übersetzung.
// ideal_clip_s als Zahl (float), Obergrenze ~90s beachten falls die
// Messwerte darüber liegen — nenne den gemessenen Median trotzdem ehrlich,
// die Deckelung passiert außerhalb dieses Prompts.

Antworte NUR mit dem JSON-Objekt. Kein Markdown-Codeblock, kein Vorspann,
kein Nachwort.
```

**Einsatz-Hinweise:**
- Wird pro `learn`-Lauf einmal aufgerufen, NUR für Ordner-Ebenen, die nach F7-Klassifikation als CUT-Stil erkannt wurden (Median-Dauer ≤ ~2 min) — FORMAT-Profile (ganze Videos) werden NIE in diesen Prompt gegeben, da sie sonst fälschlich eine `ideal_clip_s` erhalten würden.
- Mechanischer Fallback (ohne LLM oder `--no-llm`) muss dieselben Schlüssel liefern: `ideal_clip_s` = Median der `duration_s`, `pace` = grobe Kategorisierung aus `cuts_per_min`-Schwellwerten, `humor_notes`/`caption_style` leer.
- Sanitizer klemmt `ideal_clip_s` hart auf die im Code definierte Obergrenze (~90s), unabhängig davon was das Modell zurückgibt — der Prompt-Hinweis reduziert nur die Häufigkeit unrealistischer Werte, garantiert die Grenze aber nicht.


---

Ende des Prompts.
