"""ffmpeg/ffprobe-Anbindung: Ingest, Audio-Extraktion, Szenen-Rate, Schnitt.

ffmpeg ist die EINZIGE harte Voraussetzung fuer echte VODs. Alle Funktionen
nehmen ein injizierbares ``run_fn`` (Signatur wie subprocess.run) — Tests
laufen komplett ohne echte Binaries.

AMD-sicher: Encoding nutzt AMD AMF (h264_amf) wenn verfuegbar, sonst
CPU libx264. Andere Hardware-Encoder existieren in diesem Code bewusst
nicht, auch nicht als Fallback-Zweig.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

from .errors import ClipLabError, MissingInputError
from .util import finite, slugify

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts", ".m4v"}

_AUDIO_STREAM_RE = re.compile(r"^(a:)?(\d{1,3})$")


def default_run(argv, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(argv, **kwargs)


def have_ffmpeg(which=shutil.which) -> str | None:
    return which("ffmpeg")


def have_ffprobe(which=shutil.which) -> str | None:
    return which("ffprobe")


def _need_ffmpeg(which=shutil.which) -> str:
    exe = have_ffmpeg(which)
    if exe is None:
        raise ClipLabError(
            "ffmpeg wurde nicht gefunden — ohne ffmpeg kann keine echte VOD "
            "verarbeitet werden.",
            hint="ffmpeg installieren (winget install ffmpeg / apt install ffmpeg) "
            "und neu starten. `doctor` prueft die Umgebung.",
        )
    return exe


def _need_ffprobe(which=shutil.which) -> str:
    exe = have_ffprobe(which)
    if exe is None:
        raise ClipLabError(
            "ffprobe wurde nicht gefunden (gehoert zu ffmpeg).",
            hint="ffmpeg-Paket installieren — es enthaelt ffprobe.",
        )
    return exe


def normalize_audio_stream(spec: str) -> str:
    """'a:1' oder '1' -> 'a:1'; leer = Default-Spur; sonst ClipLabError."""
    if not spec or not str(spec).strip():
        return ""
    m = _AUDIO_STREAM_RE.match(str(spec).strip())
    if not m:
        raise ClipLabError(
            f"Ungueltige Tonspur-Angabe: {spec!r}",
            hint="Erwartet z.B. 'a:1' (zweite Tonspur, nur Mikro) oder 'a:0'.",
        )
    return f"a:{m.group(2)}"


def ffprobe_duration(path: Path | str, run_fn=default_run, which=shutil.which) -> float:
    """Dauer in Sekunden via ffprobe; freundliche Fehler."""
    exe = _need_ffprobe(which)
    path = Path(path)
    if not path.is_file():
        raise MissingInputError(f"Datei nicht gefunden: {path}")
    argv = [
        exe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = run_fn(argv, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClipLabError(f"ffprobe liess sich nicht ausfuehren ({exc}).")
    dur = finite((proc.stdout or "").strip(), default=float("nan"))
    if proc.returncode != 0 or not math.isfinite(dur) or dur <= 0:
        raise ClipLabError(
            f"ffprobe konnte die Dauer von {path.name} nicht bestimmen.",
            hint="Ist das eine Videodatei, die ffmpeg lesen kann (mp4/mkv/webm/...)?",
        )
    return float(dur)


def extract_audio(
    vod: Path | str,
    wav_out: Path | str,
    audio_stream: str = "",
    sr: int = 16000,
    run_fn=default_run,
    which=shutil.which,
) -> Path:
    """Audio als mono 16-kHz-WAV extrahieren; Tonspur waehlbar (a:N)."""
    exe = _need_ffmpeg(which)
    vod = Path(vod)
    wav_out = Path(wav_out)
    stream = normalize_audio_stream(audio_stream)
    argv = [exe, "-y", "-v", "error", "-i", str(vod)]
    if stream:
        argv += ["-map", f"0:{stream}"]
    argv += ["-vn", "-ac", "1", "-ar", str(sr), "-acodec", "pcm_s16le", str(wav_out)]
    try:
        proc = run_fn(argv, timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClipLabError(f"ffmpeg-Audio-Extraktion fehlgeschlagen ({exc}).")
    if proc.returncode != 0 or not wav_out.is_file() or wav_out.stat().st_size == 0:
        stderr = (proc.stderr or "").strip().splitlines()
        detail = stderr[-1] if stderr else "unbekannter ffmpeg-Fehler"
        hint = "VOD-Datei pruefen."
        if stream:
            hint = (
                f"Hat die Aufnahme wirklich eine Tonspur {stream}? "
                "OBS-Mehrspur-Aufnahmen brauchen 'Spur 2' aktiviert. "
                "Ohne --audio-stream wird die Standardspur genutzt."
            )
        raise ClipLabError(f"Audio-Extraktion fehlgeschlagen: {detail}", hint=hint)
    return wav_out


def read_wav_mono(path: Path | str):
    """WAV (PCM16) als float-Array [-1..1] + Samplerate lesen."""
    try:
        import numpy as np  # lazy — doctor/selftest laufen auch ohne numpy
    except ImportError:
        raise ClipLabError(
            "numpy ist nicht installiert — noetig fuer die Audio-Analyse.",
            hint="python -m pip install numpy (oder bootstrap.py ausfuehren).",
        )
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as wf:
            sr = wf.getframerate()
            n = wf.getnframes()
            ch = wf.getnchannels()
            width = wf.getsampwidth()
            raw = wf.readframes(n)
    except (OSError, wave.Error, EOFError) as exc:
        raise ClipLabError(f"WAV-Datei {path.name} nicht lesbar ({exc}).")
    if width != 2:
        raise ClipLabError(f"WAV-Datei {path.name}: erwarte 16-bit PCM, ist {8 * width}-bit.")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, int(sr)


def scene_cut_rate(
    path: Path | str,
    duration: float,
    sample_s: float = 120.0,
    threshold: float = 0.30,
    run_fn=default_run,
    which=shutil.which,
) -> float | None:
    """Schnitte/Minute via ffmpeg-Szenenerkennung ueber ein Sample-Fenster.

    0.0 ist eine echte Messung (lange ungeschnittene Takes).
    None = Messung nicht moeglich (kein ffmpeg / Fehler) -> ohne Pace lernen.
    """
    exe = have_ffmpeg(which)
    if exe is None:
        return None
    span = min(max(1.0, duration), sample_s) if duration > 0 else sample_s
    argv = [
        exe,
        "-hide_banner",
        "-t", f"{span:.2f}",
        "-i", str(path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an",
        "-f", "null",
        "-",
    ]
    try:
        proc = run_fn(argv, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    cuts = len(re.findall(r"pts_time:", proc.stderr or ""))
    minutes = span / 60.0
    if minutes <= 0:
        return None
    return cuts / minutes


# ---------------------------------------------------------------------------
# Encoder-Wahl (AMD-sicher: nur h264_amf oder libx264)

AMF_ARGS = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"]
X264_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"]


def list_encoders(run_fn=default_run, which=shutil.which) -> str:
    exe = have_ffmpeg(which)
    if exe is None:
        return ""
    try:
        proc = run_fn([exe, "-hide_banner", "-encoders"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


def pick_encoder_args(choice: str = "auto", run_fn=default_run, which=shutil.which) -> tuple[str, list[str]]:
    """(name, ffmpeg-Argumente) fuer den Video-Encoder.

    choice: auto | amf | h264_amf | x264 | libx264 — alles andere wird
    abgelehnt (Allowlist, keine anderen Hardware-Encoder).
    """
    choice = (choice or "auto").strip().lower()
    if choice in ("amf", "h264_amf"):
        return "h264_amf", AMF_ARGS
    if choice in ("x264", "libx264"):
        return "libx264", X264_ARGS
    if choice != "auto":
        raise ClipLabError(
            f"Unbekannter Encoder {choice!r}.",
            hint="Erlaubt: auto, amf (AMD-Hardware), x264 (CPU).",
        )
    if " h264_amf " in list_encoders(run_fn, which):
        return "h264_amf", AMF_ARGS
    return "libx264", X264_ARGS


VERTICAL_FILTER = "crop=ih*9/16:ih,scale=1080:1920"


def cut_clip(
    vod: Path | str,
    out_path: Path | str,
    t0: float,
    t1: float,
    duration: float,
    encoder_args: list[str] | None = None,
    vertical: bool = False,
    run_fn=default_run,
    which=shutil.which,
) -> list[str]:
    """Einen Clip [t0, t1] herausschneiden (Re-Encode).

    Erkennt ffmpegs Stumm-Fehlschlag:
    - Range komplett ausserhalb des Videos -> Fehler statt leerer Datei
    - abgeschnittene Ranges -> ehrliche Notiz in der Rueckgabe
    Rueckgabe: Liste von Notizen (kann leer sein).
    """
    exe = _need_ffmpeg(which)
    vod = Path(vod)
    out_path = Path(out_path)
    notes: list[str] = []
    if not (math.isfinite(t0) and math.isfinite(t1)) or t1 <= t0 or t0 < 0:
        raise ClipLabError(f"Ungueltiger Schnittbereich: t0={t0}, t1={t1}.")
    if duration > 0 and t0 >= duration:
        raise ClipLabError(
            f"Schnittbereich beginnt bei {t0:.1f}s — das Video ist aber nur "
            f"{duration:.1f}s lang. ffmpeg wuerde still eine leere Datei erzeugen.",
            hint="Gehoert der Schnittplan wirklich zu dieser VOD?",
        )
    if duration > 0 and t1 > duration:
        notes.append(
            f"Clip-Ende {t1:.1f}s liegt hinter dem Videoende ({duration:.1f}s) — "
            f"auf {duration:.1f}s gekuerzt."
        )
        t1 = duration
    enc = list(encoder_args) if encoder_args else list(X264_ARGS)
    argv = [exe, "-y", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(vod), "-t", f"{t1 - t0:.3f}"]
    if vertical:
        argv += ["-vf", VERTICAL_FILTER]
    argv += enc + ["-c:a", "aac", "-b:a", "192k", str(out_path)]
    try:
        proc = run_fn(argv, timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClipLabError(f"ffmpeg-Schnitt fehlgeschlagen ({exc}).")
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        stderr = (proc.stderr or "").strip().splitlines()
        detail = stderr[-1] if stderr else "leere Ausgabedatei"
        try:
            if out_path.is_file() and out_path.stat().st_size == 0:
                out_path.unlink()
        except OSError:
            pass
        raise ClipLabError(f"Schnitt von {out_path.name} fehlgeschlagen: {detail}")
    return notes


def make_clip_filename(rank: int, category: str, title: str, channel: str = "") -> str:
    parts = [f"clip_{rank:02d}", slugify(category, max_len=20), slugify(title, max_len=40)]
    if channel:
        parts.append(slugify(channel, max_len=20))
    return "_".join(p for p in parts if p) + ".mp4"
