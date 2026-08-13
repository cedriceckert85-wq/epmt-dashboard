# DESIGN_NOTES — LoL Clip Lab V2B (unabhaengige Zweit-Implementierung)

Diese Notizen dokumentieren die Architektur-Entscheidungen und bewussten
Abweichungen. Die Spezifikation definierte WAS; alles WIE hier ist eigene
Entscheidung dieser Implementierung.

## Modulschnitt

```
cliplab/
  errors.py      Freundliche Fehler (ClipLabError=Exit 1, MissingInputError=Exit 2)
  util.py        Timecodes, Slugs, finite()-Zahlenhygiene
  sanitize.py    ALLE LLM-Feld-Reiniger + bekannte Tag-Mengen (Kategorien, SFX)
  config.py      config.toml -> Config-Dataclass; kaputt = Warnung + Defaults
  jsonextract.py Erstes balanciertes Top-Level-JSON aus Chat-Output
  llm.py         CliLLM-Runner (stdin oder {prompt}, shutil.which, Timeout)
  media.py       ffmpeg/ffprobe: Ingest, WAV, Szenen-Rate, Schnitt, Encoder-Wahl
  transcribe.py  faster-whisper (lazy, CPU int8) + Transkript-JSON-Lader
  reactions.py   numpy-Reaktionserkennung (Median/MAD-Baseline)
  events.py      Game-Events JSON/CSV + Default-Gewichte
  timeline.py    Timeline-Dokument + zeilen-alignierte Chunks
  editorial.py   Kandidaten, Session-Pass, Moment-Pass, Match-Geometrie
  dualbrain.py   Zweitmeinung (F9): identischer Prompt, Blend-Semantik
  memory.py      Kanal-Gedaechtnis (BrainStore) + Konsolidierung
  styles.py      Stil-Lernen: CUT-Stile vs. FORMAT-Profile
  ranking.py     Signal+Semantik-Score, 10-min-Cap, top_k ~ Dauer
  planning.py    EDL: Punchline-Decay, Setup-Vorlauf, Fenster-Schieben
  channels.py    Kanal-Plaene (chronologisch) + YouTube-Kapitel
  output.py      edit_sheet.md / edit_plan.json / clips.csv / chapters.txt
  pipeline.py    Orchestrierung: analyze_vod -> run_creative_pipeline
  cutting.py     cut-Kommando (Stumm-Fehlschlag-Erkennung, 9:16)
  fetchcmd.py    yt-dlp-Fetch (--, %%-Escaping, Slug-Traversal-Schutz)
  doctor.py      Umgebungs-Check (ffmpeg = einziger Fatal)
  selftest.py    F15-Selbsttest mit Demo-LLM + Fixtures
  cli.py         argparse + zentrale Fehlerbehandlung
```

Kernidee: **`run_creative_pipeline` arbeitet nur auf Werten** (Transkript,
Reaktionen, Events, Dauer) und ist damit ohne Binaries testbar; alle
IO-/Binary-Zugriffe stecken in einer injizierbaren `Deps`-Struktur. Der
Selftest und ~alle Tests laufen exakt ueber den Produktionspfad, nur mit
Fakes.

## Wichtige Einzel-Entscheidungen

- **JSON-Extraktion:** iterativer Scanner (kein Regex, keine Rekursion) mit
  String-/Escape-Tracking; maximal 32 Startpositionen (kein O(n^2) bei
  Klammer-Fluten); `RecursionError` aus `json.loads` (tiefes Nesting) wird
  wie „kein JSON" behandelt.
- **Reaktionen:** Frame-Energie (100 ms Fenster / 50 ms Hop) in dBFS;
  Baseline = blockweiser Median NUR ueber „aktive" Frames (>= Floor),
  Streuung = MAD mit 2-dB-Untergrenze. Dadurch erzeugt ein gemuteter Mic
  (alles unter -50 dBFS) exakt nichts, und ein konstanter Ton hat Excess 0.
  Peak-Kriterium: Excess >= threshold UND robuster z-Score >= 2.5.
- **Kandidaten-Geometrie:** Reaktionen ergeben echte Fenster, einzelne
  Events sind punktfoermig (t0 == t1). Match-Regeln exakt nach Spec:
  Punkt-in-Fenster inklusive Kanten; Kanten-Beruehrung zweier echter
  Fenster zaehlt nicht; identische Fenster sind Duplikate und werden vor
  dem Ranking entfernt (verbrennen keine Plaetze).
- **Moment-Pass-Budget:** 75 % des Zeichen-Budgets werden fair auf die
  Kandidaten verteilt (naechste Zeilen zuerst, mindestens eine Zeile pro
  Kandidat — auch late/sparse Kandidaten behalten Kontext), der Rest wird
  als gleichmaessige Stichprobe der uebrigen Timeline aufgefuellt.
- **Ungematchte Kandidaten im LLM-Modus:** Kandidaten, die das LLM trotz
  Kontext nicht aufgegriffen hat, fallen weg (das LLM hat sie gesehen und
  verworfen) — sie werden nicht als titel-lose Signal-Momente ins Ranking
  gezwungen. Im Signal-only-Modus werden dagegen ALLE Kandidaten zu
  Momenten.
- **Signal-only-Momente:** Wenn das LLM antwortet, aber keine brauchbaren
  Momente liefert (Muell/leer), faellt die Pipeline auf Signal-only zurueck
  und kennzeichnet das im Sheet — die Spec verlangt das nur fuer „CLI
  fehlt", wir behandeln „CLI liefert Muell" genauso (bewusste Erweiterung).
- **Negative Event-Gewichte** (death/lose) erzeugen keine eigenen
  Kandidaten, erscheinen aber in der Timeline — das LLM darf einen luftigen
  Fail-Moment trotzdem selbst entdecken.
- **Ranking:** final = 0.45·norm(signal) + 0.55·semantic/10; Signal wird
  max-normiert (Division nur bei > 0); Tiebreak (-final, t0, Titel, t1) ist
  total und stabil. top_k = max(min_clips, Stunden · clips_per_hour).
- **Planung:** Punchline setzt das Clip-Ende (punch + decay), danach
  Laengen-Klemmen „von vorne" (Setup kuerzen, Pointe behalten) und
  **Schieben** des Fensters in [0, Dauer]. Der Setup-Vorlauf pro Kategorie
  gilt nur fuer Nicht-LLM-Fenster (LLM-Fenster enthalten ihr Setup schon;
  ein LLM-„Fenster" unter 1 s behandeln wir wie einen Punkt).
- **Stil-Override der Maximallaenge:** nur nach oben (ideal_len > max_clip_s),
  gedeckelt bei `style_max_cap_s` (90 s). Ein vom Nutzer bewusst groesser
  gesetztes `max_clip_s` bleibt unangetastet.
- **Ueberlappende Clips:** der besser gerankte Clip gewinnt, der schlechtere
  entfaellt komplett (kein Fenster-Verschmelzen — Fenster sind kuratiert);
  Raenge werden danach neu nummeriert.
- **Gedaechtnis:** `sessions`-Map im Gehirn traegt die analysierten
  VOD-Namen; Re-Analyse (gleicher Name) macht nur Summary-Refresh.
  Konsolidierung: LLM-Mapping (nach Bedeutung) mit mechanischem Fallback
  (Slug-Gleichheit oder -Enthaltensein ab 4 Zeichen). `max. 1 Bump pro Gag`
  via Session-Set. lore_refs von Zweit-Gehirn-Momenten zaehlen NICHT
  (Gedaechtnis bleibt Primaer-only, F9).
- **Doppel-Gehirn:** Standard-Auslieferung DEAKTIVIERT (`llm2_cmd = []` in
  Code-Default UND config.toml) — bewusste Nutzer-Vorgabe („Claude-only");
  die komplette F9-Blending-Logik existiert und ist getestet, Codex ist als
  Opt-in im README dokumentiert (Abweichung vom Spec-Beispiel-Default).
- **Kapitel:** Erster Clip < 10 s nach Start wird selbst der Opener, sonst
  eigenes `00:00 Start`-Kapitel; danach nur Marker mit >= 10 s Abstand
  (naehere falten ins vorherige Kapitel).
- **Selftest:** nutzt Code-Defaults statt config.toml (immun gegen
  Umbenennungen), fixe Uhr `2026-01-01` (byte-deterministisch), Scratch-
  Gedaechtnis in einem frischen Ordner, In-Process-Demo-LLM mit absichtlich
  geschwaetzigen Antworten (fuehrt auch die JSON-Extraktion vor). Ausgaben
  liegen unter `selftest_output/` (per `--out`), als Arbeitsprobe im Repo.
- **CLI-Erweiterung:** globales `--config PFAD` (nicht in der Spec, aber
  noetig fuer saubere Tests und Mehrfach-Setups). `batch` liefert Exit 1,
  sobald mindestens eine Datei scheiterte („Sammel-Exit"), arbeitet aber
  alle ab.
- **Windows:** LLM-Executables werden via `shutil.which` zum vollen Pfad
  aufgeloest (`claude.cmd`-Shims!); `START.bat` verzichtet komplett auf
  `enabledelayedexpansion` (frisst `!` in Dateinamen) und auf nackte
  Klammern in `echo`-Zeilen innerhalb von if-Bloecken; `%~1` ist ueberall
  gequotet. Konsolen-Ausgabe faellt bei Legacy-Codepages auf ASCII zurueck.
- **AMD-Sicherheit:** Whisper fest `device="cpu", compute_type="int8"`;
  Encoder-Wahl ist eine Allowlist aus genau `h264_amf` und `libx264` —
  andere Hardware-Encoder existieren im Code nicht, auch nicht als
  Fallback-Zweig.

## Bewusste Interpretationen unklarer Spec-Punkte

1. „Ueberlappende Clips mergen (besserer gewinnt)" — interpretiert als
   „besserer verdraengt schlechteren", nicht als Fenster-Union (Begruendung
   oben).
2. „weight uebersteuert" bei Events: ein explizites weight-Feld gewinnt
   immer gegen die Kind-Defaults, auch wenn es 0 oder negativ ist.
3. Format der Kapitel-Titel: Clip-Titel; das Pflicht-Kapitel bei 00:00
   heisst „Start", wenn kein frueher Clip existiert.
4. `fetch` ohne `--style` legt Downloads in den `references/`-Root (dort
   werden sie beim Lernen als Stil „default" behandelt).
5. Die Spec nennt `chunk ~150k Zeichen` — konfigurierbar via
   `[llm].chunk_chars`, Untergrenze 5000 (Schutz vor Unsinn-Configs).

## Bekannte Grenzen

- Die Szenenerkennung fuer Referenz-Clips sampelt die ersten 120 s
  (konfiguriert im Aufruf), nicht das ganze Video — bewusster
  Geschwindigkeits-Kompromiss.
- `learn` mit LLM destilliert pro Stil einen Prompt; bei sehr vielen
  Referenzen pro Stil gehen nur die ersten 5 Transkript-Proben hinein.
- Der Selftest beweist den Kreativ-Pfad ohne ffmpeg; der echte
  Medien-Pfad (Ingest/Schnitt/2-Spuren) wird von der Testsuite abgedeckt,
  wenn ffmpeg vorhanden ist (synthetisches Testvideo), sonst uebersprungen.
