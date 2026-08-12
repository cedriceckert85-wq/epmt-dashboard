"""Style learning from reference videos.

Drop example clips you LIKE into the references folder (your best uploads or
other creators' edits), run `clip_lab learn`, and the tool fingerprints each
one — duration, editing pace via ffmpeg scene detection, a transcript sample —
then asks the LLM to distill ONE style guide (ideal clip length, pace, humor
traits, caption style). The guide is saved as style_profile.json and injected
into the editorial moment pass of every later `analyze`, so suggestions aim at
YOUR target style instead of a generic one.

Degrades gracefully: no LLM -> a mechanical profile (median length/pace); no
whisper -> fingerprints without transcript samples; a corrupt profile file is
simply ignored. ffmpeg/ffprobe are needed to fingerprint real videos.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .util import read_json, which, write_json

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts", ".m4v"}

STYLE_PROMPT = """You are an expert short-form video editor. Below are FINGERPRINTS
of reference clips a creator likes — this is the TARGET STYLE for their channel:
per clip the duration, the editing pace (cuts per minute) and a transcript sample.

Distill ONE style guide an editor could follow when cutting new clips.
Return ONLY JSON:
{{"target_clip_s": <ideal clip length in seconds>,
  "pace": "one line about editing pace/energy",
  "humor_style": ["short trait", "..."],
  "caption_style": "one line about captions/text-on-screen wording",
  "notes": "anything else that stands out"}}

REFERENCE CLIPS:
{refs}
"""


def list_videos(folder):
    """All video files directly in `folder`, sorted by name."""
    p = Path(folder)
    if not p.is_dir():
        return []
    return sorted(x for x in p.iterdir()
                  if x.is_file() and x.suffix.lower() in VIDEO_EXTS)


def probe_duration(path, *, run=subprocess.run):
    """Tolerant duration probe — None instead of raising (a broken reference
    file should not kill the whole learn run)."""
    if not which("ffprobe"):
        return None
    try:
        p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=60)
        return float((p.stdout or "").strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def detect_cut_pace(path, duration, *, threshold=0.35, probe_s=120,
                    run=subprocess.run):
    """Editing pace via ffmpeg scene detection on a middle sample of the clip.
    Returns {'cuts_per_min', 'avg_shot_s'} or None."""
    if not which("ffmpeg"):
        return None
    span = float(min(probe_s, duration)) if duration else float(probe_s)
    if span <= 0:
        return None
    start = max(0.0, ((duration or span) - span) / 2)
    try:
        p = run(["ffmpeg", "-hide_banner", "-ss", f"{start:.2f}",
                 "-t", f"{span:.2f}", "-i", str(path),
                 "-vf", f"select='gt(scene,{threshold})',showinfo",
                 "-an", "-f", "null", "-"],
                capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    cuts = len(re.findall(r"Parsed_showinfo.*?pts_time:", p.stderr or ""))
    return {"cuts_per_min": round(cuts / (span / 60.0), 2),
            "avg_shot_s": round(span / (cuts + 1), 2)}


def _make_transcriber(cfg):
    """One shared whisper model for all reference clips (or None)."""
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    model = WhisperModel(cfg.whisper_model, device=cfg.whisper_device,
                         compute_type=cfg.whisper_compute_type)

    def _transcribe_wav(wav_path):
        segments, _ = model.transcribe(str(wav_path), vad_filter=True)
        return " ".join(s.text.strip() for s in segments)

    return _transcribe_wav


def _sample_text(path, duration, transcriber, *, sample_s=90, run=subprocess.run):
    """Transcribe a short middle sample of the clip (or None)."""
    if transcriber is None or not which("ffmpeg"):
        return None
    start = max(0.0, ((duration or sample_s) - sample_s) / 2)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "sample.wav"
        try:
            p = run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{sample_s}",
                     "-i", str(path), "-ac", "1", "-ar", "16000", "-vn",
                     "-c:a", "pcm_s16le", str(wav)],
                    capture_output=True, text=True, timeout=300)
            if p.returncode != 0 or not wav.exists():
                return None
            return transcriber(wav)
        except (OSError, subprocess.TimeoutExpired):
            return None


def fingerprint(path, cfg, *, transcriber=None, run=subprocess.run):
    """One reference clip -> a compact fingerprint dict."""
    path = Path(path)
    dur = probe_duration(path, run=run)
    fp = {"file": path.name}
    if dur:
        fp["duration_s"] = round(dur, 2)
    pace = detect_cut_pace(path, dur, threshold=cfg.style_scene_threshold,
                           probe_s=cfg.style_probe_s, run=run)
    if pace:
        fp.update(pace)
    text = _sample_text(path, dur, transcriber, run=run)
    if text:
        fp["transcript_sample"] = text[:600]
    return fp


def learn_styles(folder, cfg, llm, *, log=lambda *a: None, run=subprocess.run):
    """Fingerprint every video in `folder` and distill the style profile.
    Returns (profile_or_None, fingerprints)."""
    vids = list_videos(folder)
    if not vids:
        return None, []
    transcriber = _make_transcriber(cfg)
    if transcriber is None:
        log("[style] faster-whisper not available — fingerprints without transcript samples")
    fps = []
    for v in vids:
        log(f"[style] fingerprinting {v.name} …")
        fps.append(fingerprint(v, cfg, transcriber=transcriber, run=run))
    profile = _consolidate(fps, llm, cfg, log)
    return profile, fps


def _consolidate(fps, llm, cfg, log):
    mechanical = _mechanical_profile(fps)
    if not (llm and getattr(cfg, "use_llm", True) and llm.available()):
        return mechanical
    try:
        res = llm.ask_json(STYLE_PROMPT.format(
            refs=json.dumps(fps, ensure_ascii=False)[:20000]))
        if not isinstance(res, dict):
            log("[style] LLM returned no usable JSON — mechanical profile")
            return mechanical
        return _sanitize_profile(res, mechanical)
    except Exception as e:  # noqa: BLE001 — learning must never lose the run
        log(f"[style] LLM consolidation failed ({type(e).__name__}) — mechanical profile")
        return mechanical


def _mechanical_profile(fps):
    prof = {"learned_from": len(fps)}
    durs = sorted(f["duration_s"] for f in fps if f.get("duration_s"))
    cpms = sorted(f["cuts_per_min"] for f in fps if f.get("cuts_per_min"))
    if durs:
        prof["target_clip_s"] = round(durs[len(durs) // 2], 1)
    if cpms:
        prof["pace"] = f"~{cpms[len(cpms) // 2]:.1f} cuts/min in the reference clips"
    return prof


def _num_or(v, default):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return f


def _sanitize_profile(res, fallback):
    out = {"learned_from": fallback.get("learned_from", 0)}
    t = _num_or(res.get("target_clip_s"), None)
    if t is not None:
        out["target_clip_s"] = round(min(90.0, max(5.0, t)), 1)
    elif "target_clip_s" in fallback:
        out["target_clip_s"] = fallback["target_clip_s"]
    for key, cap in (("pace", 200), ("caption_style", 200), ("notes", 400)):
        v = res.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()[:cap]
    traits = res.get("humor_style")
    if isinstance(traits, list):
        traits = [str(x).strip()[:80] for x in traits
                  if isinstance(x, str) and x.strip()][:10]
        if traits:
            out["humor_style"] = traits
    return out


def save_profile(path, profile):
    write_json(path, profile)


def load_profile(path):
    """Load a saved profile; missing/corrupt -> None (analyze just runs plain)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = read_json(p)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return _sanitize_profile(raw, {"learned_from": _int_learned(raw)})


def _int_learned(raw):
    n = _num_or(raw.get("learned_from"), 0)
    return max(0, int(n))


def style_brief(profile, max_chars=1500):
    """Prompt-ready STYLE GUIDE block ('' when there is no profile)."""
    if not profile:
        return ""
    L = [f"STYLE GUIDE (learned from {profile.get('learned_from', '?')} reference "
         "clips — aim the suggestions at this):"]
    if profile.get("target_clip_s"):
        L.append(f"- ideal clip length ≈ {profile['target_clip_s']}s")
    if profile.get("pace"):
        L.append(f"- pace: {profile['pace']}")
    for t in profile.get("humor_style", []):
        L.append(f"- humor: {t}")
    if profile.get("caption_style"):
        L.append(f"- captions: {profile['caption_style']}")
    if profile.get("notes"):
        L.append(f"- notes: {profile['notes']}")
    return "\n".join(L)[:max_chars]
