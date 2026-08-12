"""Style learning: reference-clip fingerprints -> style profile -> STYLE GUIDE
in the moment prompt. IO (ffprobe/ffmpeg) is injected via the `run` parameter,
the LLM via the runner — everything here runs without any real tooling."""
import json
from types import SimpleNamespace

from clip_lab.config import Config
from clip_lab.llm_client import LLMClient
from clip_lab.style import (detect_cut_pace, fingerprint, learn_styles,
                            list_videos, load_profile, probe_duration,
                            save_profile, style_brief, _mechanical_profile,
                            _sanitize_profile)


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def fake_run(stdout="", stderr="", returncode=0):
    def _run(cmd, **kw):
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)
    return _run


# ---------- listing ----------

def test_list_videos_filters_and_sorts(tmp_path):
    for name in ("b.mp4", "a.MKV", "notes.txt", "c.webm", "sub"):
        p = tmp_path / name
        if name == "sub":
            p.mkdir()
        else:
            p.write_bytes(b"x")
    vids = [v.name for v in list_videos(tmp_path)]
    assert vids == ["a.MKV", "b.mp4", "c.webm"]


def test_list_videos_missing_folder():
    assert list_videos("/definitely/not/there") == []


# ---------- probing (ffprobe/ffmpeg injected) ----------

def test_probe_duration_parses(monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    assert probe_duration("v.mp4", run=fake_run(stdout="63.5\n")) == 63.5


def test_probe_duration_tolerates_garbage(monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    assert probe_duration("v.mp4", run=fake_run(stdout="not a number")) is None


def test_detect_cut_pace_counts_showinfo_lines(monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    stderr = "\n".join(
        f"[Parsed_showinfo_1 @ 0x1] n:{i} pts:{i} pts_time:{i}.0" for i in range(10))
    pace = detect_cut_pace("v.mp4", 120.0, probe_s=60, run=fake_run(stderr=stderr))
    # 10 cuts in 60s -> 10 cuts/min
    assert pace["cuts_per_min"] == 10.0
    assert pace["avg_shot_s"] == round(60 / 11, 2)


def test_detect_cut_pace_without_ffmpeg(monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: None)
    assert detect_cut_pace("v.mp4", 120.0) is None


def test_fingerprint_collects_available_pieces(monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[0:2])
        if cmd[0] == "ffprobe":
            return SimpleNamespace(stdout="30.0", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="pts_time nothing", returncode=0)

    fp = fingerprint("clip.mp4", cfg(), transcriber=None, run=run)
    assert fp["file"] == "clip.mp4"
    assert fp["duration_s"] == 30.0
    assert "cuts_per_min" in fp
    assert "transcript_sample" not in fp     # no transcriber given


# ---------- profile building ----------

def test_mechanical_profile_uses_medians():
    fps = [{"duration_s": 20.0, "cuts_per_min": 10.0},
           {"duration_s": 30.0, "cuts_per_min": 20.0},
           {"duration_s": 90.0, "cuts_per_min": 60.0}]
    prof = _mechanical_profile(fps)
    assert prof["learned_from"] == 3
    assert prof["target_clip_s"] == 30.0
    assert "20.0 cuts/min" in prof["pace"]


def test_sanitize_clamps_and_filters():
    res = {"target_clip_s": 9999, "pace": "  fast  ", "humor_style":
           ["dry", 42, "", "self-deprecating"], "caption_style": "x" * 999,
           "notes": None}
    out = _sanitize_profile(res, {"learned_from": 4})
    assert out["target_clip_s"] == 90.0            # clamped to [5, 90]
    assert out["pace"] == "fast"
    assert out["humor_style"] == ["dry", "self-deprecating"]
    assert len(out["caption_style"]) <= 200
    assert "notes" not in out
    assert out["learned_from"] == 4


def test_sanitize_survives_infinity():
    out = _sanitize_profile({"target_clip_s": float("inf")}, {"learned_from": 1})
    assert "target_clip_s" not in out or out["target_clip_s"] <= 90


def test_learn_styles_llm_path(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr("clip_lab.style._make_transcriber", lambda c: None)
    (tmp_path / "ref1.mp4").write_bytes(b"x")
    (tmp_path / "ref2.mp4").write_bytes(b"x")

    def run(cmd, **kw):
        if cmd[0] == "ffprobe":
            return SimpleNamespace(stdout="25.0", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    llm = LLMClient(["x"], runner=lambda p: json.dumps(
        {"target_clip_s": 22, "pace": "quick", "humor_style": ["dry"]}))
    profile, fps = learn_styles(tmp_path, cfg(), llm, run=run)
    assert len(fps) == 2
    assert profile["target_clip_s"] == 22.0
    assert profile["learned_from"] == 2


def test_learn_styles_empty_folder(tmp_path):
    profile, fps = learn_styles(tmp_path, cfg(), None)
    assert profile is None and fps == []


def test_learn_styles_bad_llm_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr("clip_lab.style._make_transcriber", lambda c: None)
    (tmp_path / "r.mp4").write_bytes(b"x")

    def run(cmd, **kw):
        if cmd[0] == "ffprobe":
            return SimpleNamespace(stdout="40.0", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    llm = LLMClient(["x"], runner=lambda p: "no json here")
    profile, _ = learn_styles(tmp_path, cfg(), llm, run=run)
    assert profile["target_clip_s"] == 40.0        # mechanical fallback


# ---------- save / load / brief ----------

def test_profile_roundtrip(tmp_path):
    p = tmp_path / "style.json"
    save_profile(p, {"learned_from": 3, "target_clip_s": 25.0, "pace": "fast"})
    prof = load_profile(p)
    assert prof["target_clip_s"] == 25.0
    assert prof["learned_from"] == 3


def test_load_profile_missing_and_corrupt(tmp_path):
    assert load_profile(tmp_path / "nope.json") is None
    p = tmp_path / "bad.json"
    p.write_text("{{{not json", encoding="utf-8")
    assert load_profile(p) is None
    p.write_text('"just a string"', encoding="utf-8")
    assert load_profile(p) is None


def test_brief_empty_without_profile():
    assert style_brief(None) == ""


def test_brief_renders_and_bounds():
    prof = {"learned_from": 5, "target_clip_s": 24.0, "pace": "high energy",
            "humor_style": ["dry", "meme-heavy"], "caption_style": "short caps",
            "notes": "n" * 2000}
    brief = style_brief(prof, max_chars=800)
    assert brief.startswith("STYLE GUIDE (learned from 5 reference clips")
    assert "24.0s" in brief and "dry" in brief
    assert len(brief) <= 800


# ---------- integration: style guide reaches the moment prompt ----------

def test_style_brief_reaches_moment_prompt():
    from clip_lab.editorial import run_editorial
    from clip_lab.models import Candidate
    prompts = []

    def runner(prompt):
        prompts.append(prompt)
        if "CANDIDATE WINDOWS" in prompt:
            return "[]"
        return "{}"

    llm = LLMClient(["x"], runner=runner)
    c = Config()
    c.use_llm = True
    run_editorial([Candidate(t0=1, t1=2, signal_score=1)], "log", llm, c,
                  style_brief="STYLE GUIDE (learned from 3 reference clips):\n- x")
    moment = [p for p in prompts if "CANDIDATE WINDOWS" in p]
    assert moment and "STYLE GUIDE (learned from 3 reference clips" in moment[0]


def test_pipeline_uses_style_profile(tmp_path):
    from pathlib import Path
    from clip_lab.pipeline import analyze
    ROOT = Path(__file__).resolve().parents[2]
    style_path = tmp_path / "style.json"
    save_profile(style_path, {"learned_from": 2, "target_clip_s": 20.0})
    prompts = []

    def runner(prompt):
        prompts.append(prompt)
        if "CANDIDATE WINDOWS" in prompt:
            return "[]"
        return "{}"

    c = Config()
    c.use_llm = True
    plan, meta = analyze(str(ROOT / "samples" / "sample_vod.mkv"), c, tmp_path / "out",
                         transcript_path=ROOT / "samples" / "fixture_transcript.json",
                         events_path=ROOT / "samples" / "fixture_events.json",
                         llm=LLMClient(["x"], runner=runner),
                         style_path=style_path, log=lambda *a: None)
    assert meta["style"] == {"learned_from": 2}
    moment = [p for p in prompts if "CANDIDATE WINDOWS" in p]
    assert moment and "STYLE GUIDE" in moment[0]


def test_cli_batch_empty_folder(tmp_path):
    from clip_lab.cli import main
    assert main(["batch", str(tmp_path)]) == 2
