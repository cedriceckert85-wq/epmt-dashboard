# LoL Clip Lab (V2B — unabhaengige Zweit-Implementierung)

Komplett **lokales** Kommandozeilen-Tool: aus einer fertigen
League-of-Legends-Stream-Aufnahme (VOD) wird ein **Edit-Sheet** — die besten
Momente mit exakten Schnittpunkten, Kategorien, Stil-/Kanal-Zuordnung,
Caption/Zoom/SFX-Vorschlaegen und YouTube-Kapitelmarkern. Der kreative Kern
ist ein LLM (lokale `claude`-CLI), das das komplette Stream-Transkript liest.

Kein Streaming, kein Upload, keine Cloud — nur Analyse-/Editing-Hilfe.

---

## Schnellstart (Deutsch)

**Voraussetzungen:** Windows/Linux/Mac, Python 3.11+, **ffmpeg** (die einzige
harte Voraussetzung fuer echte VODs). Optional: `faster-whisper`
(Transkription), `claude`-CLI (LLM-Editorial), `yt-dlp` (Referenz-Downloads).

### 1. Einrichten

**Windows:** `START.bat` doppelklicken — legt die venv an, installiert
`numpy` + `faster-whisper`, prueft die Umgebung (`doctor`) und fuehrt den
Offline-Selbsttest vor. Beim Python-Installer von python.org bitte das
Haekchen **"Add python.exe to PATH"** setzen — falls es fehlt, nutzt
`START.bat` automatisch den `py`-Launcher (`py -3`).

**Linux/Mac:**

```bash
./start.sh            # oder: python3 bootstrap.py
```

### 2. VOD analysieren

```bash
python -m cliplab analyze "D:\Aufnahmen\session.mkv"
```

Oder unter Windows: **die VOD-Datei einfach auf `START.bat` ziehen.**
Einen ganzen Ordner draufziehen = Batch-Analyse aller VODs.

Ergebnis liegt neben der VOD in `session_cliplab/`:

| Datei | Inhalt |
|---|---|
| `edit_sheet.md` | Fuer Menschen: Clips mit Rang, Timecodes, Punchline, Captions, Kanal-Plaenen |
| `edit_plan.json` | Fuer Maschinen/`cut`: alle Felder |
| `clips.csv` | Fuer Tabellen: parsebar, Titel gequotet |
| `chapters.txt` | YouTube-Kapitel (erstes Kapitel exakt `00:00`) |

### 3. Nuetzliche Varianten

```bash
# OBS-Aufnahme mit 2 Tonspuren: Spur 2 (nur Mikro) fuer die Analyse nutzen
python -m cliplab analyze session.mkv --audio-stream a:1

# Fertiges Transkript verwenden (Whisper ueberspringen)
python -m cliplab analyze session.mkv --transcript transkript.json

# Game-Events dazugeben (JSON oder CSV: t,kind[,weight])
python -m cliplab analyze session.mkv --events events.json

# Ohne LLM (reines Signal-Ranking), ohne Gedaechtnis, ohne Stile
python -m cliplab analyze session.mkv --no-llm --no-memory --no-style

# Clips direkt schneiden (AMD AMF wenn vorhanden, sonst CPU x264)
python -m cliplab analyze session.mkv --cut

# Clips spaeter aus dem Plan schneiden
python -m cliplab cut session.mkv session_cliplab/edit_plan.json

# Ganzen Ordner abarbeiten
python -m cliplab batch "D:\Aufnahmen"
```

### 4. Stile lernen (Referenz-Clips)

```bash
python -m cliplab learn        # legt beim ersten Mal references/ an
# Clips einsortieren: references/insta/funny/, references/insta/montage/, references/yt/
python -m cliplab learn        # lernt: kurze Clips -> Schnitt-Stile, ganze Videos -> Ziel-Laufzeit
```

Optional Referenzen laden: `python -m cliplab fetch URL --style insta/funny`
(braucht `yt-dlp`; bitte nur mit Erlaubnis der Urheber).

### 5. Gedaechtnis, Diagnose, Selbsttest

```bash
python -m cliplab memory          # Running Gags, Catchphrases, Lore anzeigen
python -m cliplab memory --clear  # Gedaechtnis loeschen
python -m cliplab doctor          # was ist installiert, was fehlt (ffmpeg = einziger Fatal)
python -m cliplab selftest        # kompletter Offline-Beweis mit Demo-Daten
```

---

## Konfiguration

Alles steht in `config.toml` (neben diesem README); CLI-Flags uebersteuern.
Kanaele sind frei umbenennbar — Standard: `insta` (vertikal, max 60s),
`yt` (~10 min Highlights), `uncut` (ganze Session, nur Kapitel).

## Doppel-Gehirn (Zweitmeinung) — optional, standardmaessig AUS

Das Tool kann einen zweiten LLM als Zweitmeinung ueber die identischen
Momente laufen lassen (Score-Mittelung, uebersehene Momente ergaenzen —
Titel/Captions des Primaer-Gehirns werden nie ueberschrieben).
**Im Auslieferungszustand ist das deaktiviert** (`llm2_cmd = []`).
Opt-in in `config.toml`, z.B. mit der Codex-CLI:

```toml
[llm]
llm2_cmd = ["codex", "exec", "-"]
```

Ist die Zweit-CLI nicht installiert, wird sie still uebersprungen.

## Hardware-Hinweise (AMD-sicher)

- Whisper laeuft **auf der CPU** (faster-whisper, int8) — ideal fuer den
  5800X3D, die RX 9070 XT bleibt frei.
- Encoding: **AMD AMF** (`h264_amf`) wenn verfuegbar, sonst CPU `libx264`.
- Der erste Whisper-Lauf laedt das Modell **einmalig** aus dem Netz;
  danach laeuft alles offline. Ohne Internet: `--transcript` nutzen.

## Was bei fehlenden Teilen passiert (Degradation)

| fehlt | Verhalten |
|---|---|
| LLM-CLI | Signal-only-Ranking, brauchbares Sheet, klar gekennzeichnet |
| Zweit-CLI | still uebersprungen |
| faster-whisper / Modell | klare Meldung + `--transcript`-Ausweg |
| ffmpeg | einziger Fatal fuer echte VODs (`doctor` sagt es) |
| Events-Datei | laeuft ohne |
| Referenzen/Stile | laeuft ohne Stil-Tagging |
| Gedaechtnis korrupt | frisches/bereinigtes Gehirn |
| config.toml kaputt | Warnung + Defaults |

## Tests

```bash
python -m pytest        # komplette Suite (laeuft ohne echte Binaries)
```
