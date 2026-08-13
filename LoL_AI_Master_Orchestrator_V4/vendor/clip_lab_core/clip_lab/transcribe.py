"""Transcription via faster-whisper. AMD-friendly: defaults to CPU int8 (no
CUDA). On a Ryzen 7 5800X3D the 'small' model runs comfortably; VAD skips
silence to speed long VODs up a lot.

faster-whisper is imported lazily so the rest of the tool (and the tests)
work without it installed.
"""
from .models import TranscriptSegment, Word


class TranscribeError(Exception):
    pass


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(wav_path, cfg, *, log=lambda *a: None):
    """Return list[TranscriptSegment] with word timestamps."""
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        raise TranscribeError(
            "faster-whisper not installed. `pip install faster-whisper` "
            f"(inside the .venv). Original: {e}")

    lang = None if cfg.whisper_language == "auto" else cfg.whisper_language
    log(f"transcribe: loading whisper '{cfg.whisper_model}' on {cfg.whisper_device} "
        f"({cfg.whisper_compute_type}) …")
    try:
        # first run DOWNLOADS the model from Hugging Face — offline/blocked
        # networks must yield a clear message, not an httpx traceback
        model = WhisperModel(cfg.whisper_model, device=cfg.whisper_device,
                             compute_type=cfg.whisper_compute_type)
        segments, info = model.transcribe(
            str(wav_path), language=lang, vad_filter=cfg.whisper_vad,
            word_timestamps=True)
    except Exception as e:
        raise TranscribeError(
            f"whisper model '{cfg.whisper_model}' could not be loaded "
            f"({type(e).__name__}). The FIRST run downloads the model and "
            "needs internet once - after that it is cached locally. "
            "Alternatively pass --transcript your_transcript.json to skip "
            f"whisper entirely. Original error: {e}") from e

    out = []
    for s in segments:
        words = [Word(t0=float(w.start), t1=float(w.end), text=w.word)
                 for w in (s.words or []) if w.start is not None]
        out.append(TranscriptSegment(t0=float(s.start), t1=float(s.end),
                                     text=s.text.strip(), words=words))
    log(f"transcribe: {len(out)} segments, language={getattr(info, 'language', '?')}")
    return out


def load_transcript(path):
    """Load a pre-made transcript JSON (so the editorial stages can run without
    whisper, and for the self-test). Format: {'segments':[{t0,t1,text,words}]}."""
    from .util import read_json
    data = read_json(path)
    segs = data.get("segments", data) if isinstance(data, dict) else data
    out = []
    for s in segs:
        words = [Word(t0=float(w["t0"]), t1=float(w["t1"]), text=w["text"])
                 for w in s.get("words", [])]
        out.append(TranscriptSegment(t0=float(s["t0"]), t1=float(s["t1"]),
                                     text=s.get("text", ""), words=words))
    return out


def save_transcript(segments, path):
    from .util import write_json
    write_json(path, {"segments": [s.as_dict() for s in segments]})
