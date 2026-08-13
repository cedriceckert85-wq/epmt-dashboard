"""VOD ingest: probe duration and extract a mono 16 kHz PCM track for analysis.
Uses ffmpeg/ffprobe (no Python A/V deps). Reading the wav is stdlib `wave`."""
import subprocess
import wave
from pathlib import Path

from .util import which


class IngestError(Exception):
    pass


def probe_duration(vod_path):
    if not which("ffprobe"):
        raise IngestError("ffprobe not found — install ffmpeg (see README)")
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(vod_path)],
        capture_output=True, text=True)
    try:
        return float((p.stdout or "").strip())
    except ValueError:
        raise IngestError(f"could not read duration of {vod_path}: {p.stderr.strip()}")


def extract_audio(vod_path, out_wav, *, sr=16000, audio_stream=None):
    """Extract mono PCM. audio_stream lets you pick the mic track
    (e.g. 'a:1') if your VOD has separate game + mic tracks."""
    if not which("ffmpeg"):
        raise IngestError("ffmpeg not found — install ffmpeg (see README)")
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(vod_path)]
    if audio_stream:
        cmd += ["-map", f"0:{audio_stream}"]
    cmd += ["-ac", "1", "-ar", str(sr), "-vn", "-c:a", "pcm_s16le", str(out_wav)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not Path(out_wav).exists():
        raise IngestError(f"ffmpeg audio extraction failed: {p.stderr.strip()[-500:]}")
    return out_wav


def read_wav_mono(wav_path):
    """Return (samples float32 in [-1,1], sr). stdlib only."""
    import numpy as np
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        sw = w.getsampwidth()
        ch = w.getnchannels()
        raw = w.readframes(n)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sw)
    if dtype is None:
        raise IngestError(f"unsupported wav sample width {sw}")
    a = np.frombuffer(raw, dtype=dtype).astype("float32")
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    maxv = float(np.iinfo(dtype).max)
    return a / maxv, sr
