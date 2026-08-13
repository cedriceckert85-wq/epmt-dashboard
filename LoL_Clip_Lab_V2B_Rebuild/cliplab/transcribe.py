"""Transkription: faster-whisper (CPU, int8, VAD, Wort-Timestamps) —
oder ein fertiges Transkript-JSON via ``--transcript``.

Modell-Load-/Download-Fehler erzeugen eine klare Meldung mit Loesungsweg
(erster Lauf braucht einmal Internet; oder --transcript nutzen) und NIE
einen httpx-Stacktrace.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ClipLabError, MissingInputError
from .sanitize import clean_str
from .util import finite

WHISPER_MODELS = ("tiny", "base", "small", "medium")


@dataclass
class TranscriptSegment:
    t0: float
    t1: float
    text: str
    words: list[tuple[float, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"t0": round(self.t0, 2), "t1": round(self.t1, 2), "text": self.text}
        if self.words:
            d["words"] = [{"t": round(t, 2), "word": w} for t, w in self.words]
        return d


def _parse_words(raw) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        t = None
        w = None
        if isinstance(item, dict):
            t = finite(item.get("t", item.get("start")), default=float("nan"))
            w = item.get("word", item.get("w", item.get("text")))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            t = finite(item[0], default=float("nan"))
            w = item[1]
        if t is None or not math.isfinite(t) or t < 0:
            continue
        w = clean_str(w, max_len=60)
        if not w:
            continue
        out.append((float(t), w))
    return out


def parse_transcript_data(data) -> list[TranscriptSegment]:
    """Segmente aus JSON-Daten (Liste oder {"segments": [...]}), tolerant."""
    if isinstance(data, dict):
        raw = data.get("segments")
    else:
        raw = data
    if not isinstance(raw, list):
        return []
    segments: list[TranscriptSegment] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        t0 = finite(entry.get("t0", entry.get("start")), default=float("nan"))
        t1 = finite(entry.get("t1", entry.get("end")), default=float("nan"))
        text = clean_str(entry.get("text"), max_len=2000)
        if not math.isfinite(t0) or not math.isfinite(t1):
            continue
        if t0 < 0 or t1 < t0:
            continue
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                t0=float(t0),
                t1=float(t1),
                text=text,
                words=_parse_words(entry.get("words")),
            )
        )
    segments.sort(key=lambda s: (s.t0, s.t1))
    return segments


def load_transcript_json(path: Path | str) -> list[TranscriptSegment]:
    """--transcript datei.json laden. Format: Segmente mit t0/t1/text."""
    path = Path(path)
    if not path.is_file():
        raise MissingInputError(
            f"Transkript-Datei nicht gefunden: {path}",
            hint="Pfad pruefen. Format: JSON mit Segmenten {t0, t1, text}.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, RecursionError, OSError) as exc:
        raise ClipLabError(
            f"Transkript-Datei {path.name} ist kein gueltiges JSON ({exc}).",
            hint='Erwartet: {"segments":[{"t0":0,"t1":5,"text":"..."}]} oder eine Liste.',
        )
    segments = parse_transcript_data(data)
    if not segments:
        raise ClipLabError(
            f"Transkript-Datei {path.name} enthaelt keine brauchbaren Segmente.",
            hint='Erwartet: {"segments":[{"t0":0,"t1":5,"text":"..."}]} — t0/t1 in Sekunden.',
        )
    return segments


class WhisperUnavailable(ClipLabError):
    pass


def transcribe_wav(
    wav_path: Path | str,
    model_size: str = "small",
    language: str = "auto",
    model=None,
) -> tuple[list[TranscriptSegment], dict]:
    """WAV mit faster-whisper transkribieren (CPU int8, VAD, Wort-Timestamps).

    ``model`` kann injiziert werden (Tests / geteiltes Modell beim Stil-Lernen).
    """
    if model_size not in WHISPER_MODELS:
        model_size = "small"
    if model is None:
        model = load_whisper_model(model_size)
    try:
        seg_iter, info = model.transcribe(
            str(wav_path),
            language=None if language in ("", "auto") else language,
            vad_filter=True,
            word_timestamps=True,
            beam_size=5,
        )
        segments: list[TranscriptSegment] = []
        for seg in seg_iter:
            text = clean_str(getattr(seg, "text", ""), max_len=2000)
            if not text:
                continue
            words = []
            for w in getattr(seg, "words", None) or []:
                wt = finite(getattr(w, "start", None), default=float("nan"))
                wtext = clean_str(getattr(w, "word", ""), max_len=60)
                if math.isfinite(wt) and wtext:
                    words.append((float(wt), wtext))
            segments.append(
                TranscriptSegment(
                    t0=float(finite(getattr(seg, "start", 0.0))),
                    t1=float(finite(getattr(seg, "end", 0.0))),
                    text=text,
                    words=words,
                )
            )
    except ClipLabError:
        raise
    except Exception as exc:  # noqa: BLE001 — whisper wirft bunt (ctranslate2, av, ...)
        raise ClipLabError(
            f"Transkription fehlgeschlagen ({type(exc).__name__}: {exc}).",
            hint="Alternativ ein fertiges Transkript mit --transcript datei.json uebergeben.",
        )
    lang = getattr(info, "language", None) or "?"
    return segments, {"language": str(lang), "model": model_size}


def load_whisper_model(model_size: str = "small"):
    """faster-whisper-Modell laden (lazy Import; CPU, int8 — AMD-sicher).

    Import-/Download-Fehler -> klare Meldung, kein Stacktrace.
    """
    if model_size not in WHISPER_MODELS:
        model_size = "small"
    try:
        from faster_whisper import WhisperModel  # lazy import
    except ImportError:
        raise WhisperUnavailable(
            "faster-whisper ist nicht installiert.",
            hint="python -m pip install faster-whisper — oder ein fertiges "
            "Transkript mit --transcript datei.json uebergeben.",
        )
    try:
        return WhisperModel(model_size, device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001 — httpx/HF werfen viele Typen
        raise WhisperUnavailable(
            f"Whisper-Modell '{model_size}' konnte nicht geladen werden "
            f"({type(exc).__name__}).",
            hint="Der erste Lauf braucht einmal Internet fuer den Modell-Download. "
            "Danach laeuft alles offline. Alternativ: --transcript datei.json "
            "nutzen oder ein kleineres Modell (--whisper-model tiny) probieren.",
        )
