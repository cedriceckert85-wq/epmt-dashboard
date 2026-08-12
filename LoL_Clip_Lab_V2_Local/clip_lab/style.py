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
of reference clips a creator likes for their '{name}' style — this is a TARGET
STYLE for their channel: per clip the duration, the editing pace (cuts per
minute) and a transcript sample.

Distill ONE style guide an editor could follow when cutting new '{name}' clips.
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
    file should not kill the whole learn run). Rejects non-finite and
    non-positive values too: ffprobe can report 'nan' or negative durations
    for corrupt files, and those must never leak into the style profile."""
    if not which("ffprobe"):
        return None
    try:
        p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=60)
        d = float((p.stdout or "").strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if d != d or d in (float("inf"), float("-inf")) or d <= 0:
        return None
    return d


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
    """One shared whisper model for all reference clips (or None). The model
    CONSTRUCTOR downloads from Hugging Face on first use, so it must sit
    inside the guard too — offline learning still works, just without
    transcript samples (as the module docstring promises)."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(cfg.whisper_model, device=cfg.whisper_device,
                             compute_type=cfg.whisper_compute_type)
    except Exception:
        return None

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


def _style_groups(folder):
    """Reference clips grouped by style. Two levels are supported so a
    CHANNEL can hold several styles:

        references/insta/funny/    -> style 'insta_funny'
        references/insta/montage/  -> style 'insta_montage'
        references/yt/             -> style 'yt'
        references/uncut/          -> style 'uncut'

    Videos directly in a level-1 folder are that folder's own style; videos
    directly in the root are the 'default' style. Both levels can coexist."""
    folder = Path(folder)
    groups = {}
    root_vids = list_videos(folder)
    if root_vids:
        groups["default"] = root_vids
    if not folder.is_dir():
        return groups
    for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
        pname = _style_name(sub.name)
        if not pname:
            continue
        vids = list_videos(sub)
        if vids:
            groups[pname] = vids
        for sub2 in sorted(p for p in sub.iterdir() if p.is_dir()):
            cname = _style_name(sub2.name)
            vids2 = list_videos(sub2)
            if cname and vids2:
                groups[f"{pname}_{cname}"[:40]] = vids2
    return groups


def _style_name(raw):
    """Folder name -> safe style slug. Style names end up in CSV columns and
    prompts, so commas/odd characters are squashed to underscores."""
    name = re.sub(r"[^a-z0-9_\-]+", "_", str(raw).strip().lower()).strip("_")
    return name[:40]


def learn_styles(folder, cfg, llm, *, log=lambda *a: None, run=subprocess.run):
    """Fingerprint every reference clip, grouped by style subfolder, and
    distill one profile per style. Returns (profiles, fingerprints) — both
    dicts keyed by style name; empty dicts when there are no videos."""
    groups = _style_groups(folder)
    if not groups:
        return {}, {}
    transcriber = _make_transcriber(cfg)
    if transcriber is None:
        log("[style] faster-whisper not available — fingerprints without transcript samples")
    profiles, all_fps = {}, {}
    for name, vids in groups.items():
        fps = []
        for v in vids:
            log(f"[style] [{name}] fingerprinting {v.name} …")
            fps.append(fingerprint(v, cfg, transcriber=transcriber, run=run))
        profiles[name] = _consolidate(name, fps, llm, cfg, log)
        all_fps[name] = fps
    return profiles, all_fps


def _consolidate(name, fps, llm, cfg, log):
    mechanical = _mechanical_profile(fps)
    if not (llm and getattr(cfg, "use_llm", True) and llm.available()):
        return mechanical
    try:
        res = llm.ask_json(STYLE_PROMPT.format(
            name=name, refs=json.dumps(fps, ensure_ascii=False)[:20000]))
        if not isinstance(res, dict):
            log(f"[style] [{name}] LLM returned no usable JSON — mechanical profile")
            return mechanical
        return _sanitize_profile(res, mechanical)
    except Exception as e:  # noqa: BLE001 — learning must never lose the run
        log(f"[style] [{name}] LLM consolidation failed ({type(e).__name__}) — mechanical profile")
        return mechanical


def _finite(values, *, minimum):
    out = []
    for v in values:
        f = _num_or(v, None)
        if f is not None and f >= minimum:
            out.append(f)
    return sorted(out)


def _mechanical_profile(fps):
    prof = {"learned_from": len(fps)}
    durs = _finite((f.get("duration_s") for f in fps), minimum=1e-9)
    # 0 cuts/min is a REAL measurement (long uncut takes) — the defining
    # trait of a montage-of-one style must not be silently discarded
    cpms = _finite((f.get("cuts_per_min") for f in fps), minimum=0.0)
    if durs:
        prof["target_clip_s"] = round(min(90.0, max(5.0, durs[len(durs) // 2])), 1)
    if cpms:
        median = cpms[len(cpms) // 2]
        if median == 0:
            prof["pace"] = "long uncut takes (~0 cuts/min in the reference clips)"
        else:
            prof["pace"] = f"~{median:.1f} cuts/min in the reference clips"
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
    # the fallback value goes through the exact same clamp as the LLM value —
    # a NaN/Infinity that sneaked into a stored profile must not round-trip
    t = _num_or(res.get("target_clip_s"), None)
    if t is None:
        t = _num_or(fallback.get("target_clip_s"), None)
    if t is not None:
        out["target_clip_s"] = round(min(90.0, max(5.0, t)), 1)
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


def save_profiles(path, profiles):
    """Persist all learned styles (v2 file format)."""
    write_json(path, {"version": 2, "styles": profiles})


def load_profile(path):
    """Load a saved single profile; missing/corrupt -> None (analyze just runs
    plain). RecursionError guards against pathologically nested JSON files."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = read_json(p)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(raw, dict):
        return None
    return _sanitize_profile(raw, {"learned_from": _int_learned(raw)})


def load_profiles(path):
    """Load ALL learned styles as {name: profile}. Reads the v2 multi-style
    format; an old v1 single-profile file becomes {'default': profile}.
    Missing/corrupt -> {} (analyze just runs without a style guide)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = read_json(p)
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(raw, dict):
        return {}
    styles = raw.get("styles")
    if isinstance(styles, dict):
        out = {}
        for name, prof in styles.items():
            key = _style_name(name)
            if key and isinstance(prof, dict):
                out[key] = _sanitize_profile(prof, {"learned_from": _int_learned(prof)})
        return out
    prof = load_profile(path)   # v1 backward compat
    return {"default": prof} if prof else {}


def _int_learned(raw):
    n = _num_or(raw.get("learned_from"), 0)
    return max(0, int(n))


def style_brief(profile, max_chars=1500):
    """Prompt-ready STYLE GUIDE block ('' when there is no profile)."""
    if not profile:
        return ""
    L = [f"STYLE GUIDE (learned from {profile.get('learned_from', '?')} reference "
         "clips — aim the suggestions at this):"]
    L.extend(_profile_lines(profile))
    return "\n".join(L)[:max_chars]


def _profile_lines(profile):
    L = []
    if profile.get("target_clip_s"):
        L.append(f"- ideal clip length ≈ {profile['target_clip_s']}s")
    if profile.get("pace"):
        L.append(f"- pace: {profile['pace']}")
    traits = profile.get("humor_style")
    for t in (traits if isinstance(traits, list) else []):
        L.append(f"- humor: {t}")
    if profile.get("caption_style"):
        L.append(f"- captions: {profile['caption_style']}")
    if profile.get("notes"):
        L.append(f"- notes: {profile['notes']}")
    return L


def styles_brief(profiles, max_chars=2500):
    """Prompt block covering ALL learned styles. With just a 'default' style
    it reads like the classic single guide; with named styles it instructs the
    LLM to pick the best-fitting style PER MOMENT and tag it.

    The budget is split per style so EVERY style name always appears — a hard
    tail-truncation would silently make the last styles untaggable."""
    if not profiles:
        return ""
    if set(profiles) == {"default"}:
        return style_brief(profiles["default"], max_chars)
    header = ("STYLE GUIDES (learned from your reference folders). For EVERY "
              "moment decide from the content which style it should be cut in, "
              'and tag it via "style": "<name>". Names may be '
              "'<channel>_<flavor>' (e.g. insta_funny vs insta_montage) — pick "
              "the one matching both where the clip belongs and how it should "
              "feel:")
    share = max(60, (max_chars - len(header)) // max(1, len(profiles)))
    L = [header]
    for name in sorted(profiles):
        prof = profiles[name] or {}
        block = [f"[{name}] (from {prof.get('learned_from', '?')} clips)"]
        block.extend(_profile_lines(prof) or ["- (no distinctive stats)"])
        text = "\n".join(block)
        if len(text) > share:
            # trim whole lines from the end, never the [name] header line
            kept = []
            used = 0
            for line in block:
                if kept and used + len(line) + 1 > share:
                    break
                kept.append(line)
                used += len(line) + 1
            text = "\n".join(kept)
        L.append(text)
    return "\n".join(L)
