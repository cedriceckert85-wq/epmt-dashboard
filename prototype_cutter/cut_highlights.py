#!/usr/bin/env python3
"""Prototyp-Highlight-Cutter (eigenständig, unabhängig vom Orchestrator).

Findet "laute Momente" (Reaktionen, Action-Peaks) über eine
Audio-Energie-Analyse und schneidet daraus Clips:

  1. Audio als 16-kHz-Mono-PCM extrahieren (ffmpeg)
  2. Kurzzeit-Lautstärke (RMS in dB) pro 0.5-s-Fenster
  3. Gleitende Median-Baseline (~30 s) — ein Peak zählt nur, wenn er
     deutlich ÜBER der lokalen Baseline liegt (Dauerlärm zählt nicht)
  4. Peak-Auswahl mit Mindestabstand, Top-N nach Score
  5. Clips mit Vor-/Nachlauf schneiden (framegenauer Re-Encode)
  6. REPORT.md + highlights.json mit Zeitstempeln und Scores

Nutzung:
  python3 cut_highlights.py video.mp4
  python3 cut_highlights.py video.mp4 --clips 5 --pre 12 --post 6 --out clips/
"""
import argparse, json, math, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np

SR = 16000                 # Analyse-Samplerate
WIN_S = 0.5                # Analysefenster in Sekunden
BASELINE_WIN_S = 30.0      # Fensterbreite der Median-Baseline
MIN_SCORE_DB = 5.0         # Peak muss >= 5 dB über der Baseline liegen


def die(msg, code=2):
    print(f"FEHLER: {msg}", file=sys.stderr)
    raise SystemExit(code)


def run(argv, **kw):
    r = subprocess.run(argv, capture_output=True, text=kw.pop("text", True), **kw)
    return r


def probe_duration(video):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(video)])
    if r.returncode != 0:
        die(f"ffprobe scheitert an {video}: {r.stderr.strip()[:300]}")
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        die("Videodauer nicht ermittelbar")


def has_audio(video):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(video)])
    return r.returncode == 0 and r.stdout.strip() != ""


def has_video(video):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(video)])
    return r.returncode == 0 and r.stdout.strip() != ""


def write_local_cut_scripts(out_dir, source_name, merged, offset):
    """Audio-only-Modus: statt zu schneiden, Skripte erzeugen, die die
    Clips lokal aus dem ORIGINAL-Video schneiden (volle Qualität).
    offset = Startzeit des Audio-Ausschnitts im Original (Sekunden)."""
    sh = ["#!/bin/sh", f"# Clips aus {source_name} schneiden (im selben Ordner ausführen)"]
    bat = ["@echo off", f"rem Clips aus {source_name} schneiden (im selben Ordner ausfuehren)"]
    for i, (start, end, peaks) in enumerate(merged, 1):
        s, e = start + offset, end + offset
        name = f"clip_{i:02d}_{fmt_ts(s).replace(':', '-')}.mp4"
        cmd = (f'ffmpeg -ss {s:.2f} -to {e:.2f} -i "{source_name}" '
               f'-c:v libx264 -preset veryfast -crf 21 -c:a aac -b:a 160k -y "{name}"')
        sh.append(cmd)
        bat.append(cmd)
    (out_dir / "cut_clips.sh").write_text("\n".join(sh) + "\n", encoding="utf-8")
    (out_dir / "cut_clips.bat").write_text("\r\n".join(bat) + "\r\n", encoding="utf-8")


def extract_pcm(video, tmpdir):
    pcm = Path(tmpdir) / "audio.s16le"
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
             "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-y", str(pcm)])
    if r.returncode != 0:
        die(f"Audio-Extraktion scheitert: {r.stderr.strip()[:300]}")
    return pcm


def loudness_curve(pcm_path):
    data = np.fromfile(pcm_path, dtype=np.int16).astype(np.float32) / 32768.0
    win = int(SR * WIN_S)
    if len(data) < win:
        die("Audiospur zu kurz für eine Analyse")
    n = len(data) // win
    frames = data[: n * win].reshape(n, win)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    return db  # ein Wert pro WIN_S Sekunden


def moving_median(x, width):
    half = width // 2
    padded = np.pad(x, (half, half), mode="edge")
    return np.array([np.median(padded[i:i + width]) for i in range(len(x))])


def pick_highlights(db, *, top_n, min_gap_s):
    base_win = max(3, int(BASELINE_WIN_S / WIN_S) | 1)
    baseline = moving_median(db, base_win)
    score = db - baseline

    order = np.argsort(score)[::-1]
    min_gap_frames = int(min_gap_s / WIN_S)
    chosen = []
    for idx in order:
        if score[idx] < MIN_SCORE_DB and chosen:
            break
        if all(abs(int(idx) - c) >= min_gap_frames for c in chosen):
            chosen.append(int(idx))
        if len(chosen) >= top_n:
            break
    if not chosen:                       # Fallback: lautestes Fenster absolut
        chosen = [int(np.argmax(db))]
    chosen.sort()
    return [{"t": round(i * WIN_S + WIN_S / 2, 2),
             "score_db": round(float(score[i]), 2),
             "loudness_db": round(float(db[i]), 2)} for i in chosen]


def merge_ranges(ranges):
    merged = []
    for start, end, peaks in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].extend(peaks)
        else:
            merged.append([start, end, list(peaks)])
    return merged


def cut_clip(video, start, end, out_path):
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(video),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
             "-y", str(out_path)])
    if r.returncode != 0:
        die(f"Schnitt scheitert ({out_path.name}): {r.stderr.strip()[:300]}")


def fmt_ts(t):
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def main():
    p = argparse.ArgumentParser(description="Prototyp-Highlight-Cutter")
    p.add_argument("video")
    p.add_argument("--clips", type=int, default=5, help="max. Anzahl Highlights")
    p.add_argument("--pre", type=float, default=12.0, help="Vorlauf in s")
    p.add_argument("--post", type=float, default=6.0, help="Nachlauf in s")
    p.add_argument("--min-gap", type=float, default=30.0,
                   help="Mindestabstand zwischen Highlights in s")
    p.add_argument("--out", default="clips", help="Ausgabeverzeichnis")
    p.add_argument("--source-name", default=None,
                   help="Audio-only-Modus: Dateiname des Original-Videos "
                        "für das generierte lokale Schnitt-Skript")
    p.add_argument("--offset", default="0",
                   help="Audio-only-Modus: Startzeit des Audio-Ausschnitts "
                        "im Original (Sekunden oder HH:MM:SS)")
    a = p.parse_args()

    video = Path(a.video)
    if not video.exists():
        die(f"Datei nicht gefunden: {video}")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        die("ffmpeg/ffprobe nicht installiert")
    if not has_audio(video):
        die("Video hat keine Audiospur — der Prototyp arbeitet audio-basiert")

    duration = probe_duration(video)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Analysiere Audio ({fmt_ts(duration)} Video) …")
    with tempfile.TemporaryDirectory(prefix="cutter-") as td:
        db = loudness_curve(extract_pcm(video, td))

    print(f"[2/4] Suche bis zu {a.clips} Highlights …")
    highlights = pick_highlights(db, top_n=a.clips, min_gap_s=a.min_gap)

    ranges = [[max(0.0, h["t"] - a.pre), min(duration, h["t"] + a.post), [h]]
              for h in highlights]
    merged = merge_ranges([tuple(r) for r in ranges])

    audio_only = not has_video(video)
    if audio_only:
        parts = str(a.offset).split(":")
        offset = sum(float(x) * 60 ** i for i, x in enumerate(reversed(parts)))
        source = a.source_name or "DEIN_ORIGINAL_VIDEO.mp4"
        print(f"[3/4] Audio-only-Eingang: erzeuge lokales Schnitt-Skript "
              f"(Quelle: {source}, Offset {fmt_ts(offset)}) …")
        write_local_cut_scripts(out_dir, source, merged, offset)
        rows = []
        for i, (start, end, peaks) in enumerate(merged, 1):
            best = max(peaks, key=lambda h: h["score_db"])
            rows.append(f"| {i} | {fmt_ts(start + offset)}–{fmt_ts(end + offset)} | "
                        f"{fmt_ts(best['t'] + offset)} | +{best['score_db']:.1f} dB |")
            print(f"   -> Highlight {i}: {fmt_ts(best['t'] + offset)} im Original "
                  f"(+{best['score_db']:.1f} dB)")
        (out_dir / "highlights.json").write_text(json.dumps({
            "source": source, "audio_analyzed": video.name,
            "offset_s": offset, "clips": [
                {"start_s": round(s + offset, 2), "end_s": round(e + offset, 2),
                 "peaks": pk} for s, e, pk in merged]}, indent=2), encoding="utf-8")
        (out_dir / "REPORT.md").write_text(
            f"# Highlight-Report (Audio-Analyse): {video.name}\n\n"
            f"Analysierte Länge: {fmt_ts(duration)} — Zeiten beziehen sich "
            f"auf das ORIGINAL (Offset {fmt_ts(offset)}).\n\n"
            "| # | Bereich | Peak | Score |\n|---|---|---|---|\n"
            + "\n".join(rows) + "\n\n"
            f"Clips lokal schneiden: `cut_clips.bat` (Windows) oder "
            f"`sh cut_clips.sh` im Ordner von `{source}` ausführen.\n",
            encoding="utf-8")
        print(f"[4/4] Fertig: {out_dir}/ (REPORT.md, highlights.json, "
              "cut_clips.bat/.sh)")
        return

    print(f"[3/4] Schneide {len(merged)} Clip(s) …")
    report_rows, clip_meta = [], []
    for i, (start, end, peaks) in enumerate(merged, 1):
        best = max(peaks, key=lambda h: h["score_db"])
        name = f"clip_{i:02d}_{fmt_ts(best['t']).replace(':', '-')}.mp4"
        cut_clip(video, start, end, out_dir / name)
        clip_meta.append({"file": name, "start_s": round(start, 2),
                          "end_s": round(end, 2), "peaks": peaks})
        report_rows.append(
            f"| {i} | `{name}` | {fmt_ts(start)}–{fmt_ts(end)} | "
            f"{fmt_ts(best['t'])} | +{best['score_db']:.1f} dB |")
        print(f"   -> {name}  (Peak bei {fmt_ts(best['t'])}, "
              f"+{best['score_db']:.1f} dB über Baseline)")

    (out_dir / "highlights.json").write_text(json.dumps({
        "source": video.name, "duration_s": round(duration, 2),
        "clips": clip_meta}, indent=2), encoding="utf-8")
    (out_dir / "REPORT.md").write_text(
        f"# Highlight-Report: {video.name}\n\n"
        f"Videolänge: {fmt_ts(duration)} — {len(merged)} Clip(s)\n\n"
        "| # | Datei | Bereich | Peak | Score |\n|---|---|---|---|---|\n"
        + "\n".join(report_rows) + "\n\n"
        "Score = Lautstärke über der lokalen 30-s-Baseline "
        "(Reaktions-/Action-Indikator).\n", encoding="utf-8")
    print(f"[4/4] Fertig: {out_dir}/ (REPORT.md, highlights.json)")


if __name__ == "__main__":
    main()
