# Prototyp-Highlight-Cutter

Eigenständiger Schnellschuss-Cutter — **unabhängig** vom LoL AI Master
Orchestrator (der baut das „richtige" System in Phasen 01–20 mit
Riot-Sync, ASR usw.). Dieser Prototyp liefert sofort erste Ergebnisse:
Er findet laute Momente (Reaktionen, Action-Peaks) rein über die
Audiospur und schneidet daraus Clips.

## Voraussetzungen

- Python 3.10+, `numpy` (`pip install numpy`)
- `ffmpeg`/`ffprobe` im PATH

## Nutzung

```bash
python3 cut_highlights.py mein_video.mp4
# oder mit Optionen:
python3 cut_highlights.py mein_video.mp4 --clips 5 --pre 12 --post 6 --min-gap 30 --out clips/
```

| Option | Default | Bedeutung |
|---|---|---|
| `--clips` | 5 | maximale Anzahl Highlights |
| `--pre` | 12 | Sekunden Vorlauf vor dem Peak |
| `--post` | 6 | Sekunden Nachlauf nach dem Peak |
| `--min-gap` | 30 | Mindestabstand zwischen Highlights (s) |
| `--out` | `clips` | Ausgabeverzeichnis |

Ergebnis: `clips/clip_XX_HH-MM-SS.mp4` + `REPORT.md` + `highlights.json`.

## Wie es funktioniert

1. Audio → 16-kHz-Mono-PCM (ffmpeg)
2. Kurzzeit-Lautstärke (RMS in dB) pro 0,5-s-Fenster
3. Gleitende 30-s-Median-Baseline; ein Peak zählt nur, wenn er ≥ 5 dB
   **über** seiner lokalen Umgebung liegt (Dauerlärm/Musik zählt nicht)
4. Top-N-Peaks mit Mindestabstand, überlappende Clips werden gemergt
5. Framegenauer Schnitt (Re-Encode x264/aac)

## Grenzen (bewusst)

- Rein audio-basiert: kein Riot-Event-Sync, keine Spracherkennung,
  kein Bildinhalt — das ist der Job des V3-Systems (Phasen 01–20).
- Facecam-/Mikro-lastige Aufnahmen funktionieren am besten; reine
  Gameplay-Tonspuren ohne Reaktionen liefern schwächere Treffer.

Verifiziert mit einem synthetischen Testvideo (3 min, künstliche
Lärm-Bursts bei 30 s / 75 s / 130 s → erkannt bei 31 s / 76 s / 132 s).
