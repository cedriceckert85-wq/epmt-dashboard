"""Regressions for the final design review (Denkfehler pass): cut styles vs
format profiles, style-aware EDL, no double setup, output language, config
audio_stream, and duration-scaled top_k."""
import json
from types import SimpleNamespace

from clip_lab.config import Config
from clip_lab.llm_client import LLMClient
from clip_lab.models import Candidate
from clip_lab.style import (cut_styles, format_profiles, learn_styles,
                            load_profiles, save_profiles, styles_brief)


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _run_for(durs_by_style):
    def run(cmd, **kw):
        if cmd[0] == "ffprobe":
            path = str(cmd[-1])
            for key, dur in durs_by_style.items():
                if key in path:
                    return SimpleNamespace(stdout=str(dur), stderr="", returncode=0)
            return SimpleNamespace(stdout="30.0", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    return run


# ---------- cut styles vs format profiles ----------

def test_video_references_become_format_profiles(tmp_path, monkeypatch):
    # 10-minute yt uploads and 3h uncut sessions must NOT become 'ideal clip
    # length ~90s' cutting styles — they are channel FORMATS
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr("clip_lab.style._make_transcriber", lambda c: None)
    for sub in ("insta", "yt", "uncut"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "a.mp4").write_bytes(b"x")
    profiles, _ = learn_styles(
        tmp_path, cfg(), None,
        run=_run_for({"insta": 25.0, "yt": 600.0, "uncut": 10800.0}))
    assert profiles["insta"]["kind"] == "cut"
    assert profiles["yt"]["kind"] == "format"
    assert profiles["yt"]["target_video_s"] == 600.0
    assert "target_clip_s" not in profiles["yt"]           # no fabricated 90s
    assert profiles["uncut"]["kind"] == "format"
    assert set(cut_styles(profiles)) == {"insta"}
    assert set(format_profiles(profiles)) == {"yt", "uncut"}


def test_styles_brief_offers_only_cut_styles():
    brief = styles_brief({"insta_funny": {"kind": "cut", "learned_from": 5,
                                          "target_clip_s": 22.0},
                          "yt": {"kind": "format", "learned_from": 5,
                                 "target_video_s": 600.0}})
    assert "[insta_funny]" in brief
    assert "[yt]" not in brief                             # formats not taggable


def test_format_kind_survives_save_load(tmp_path):
    p = tmp_path / "s.json"
    save_profiles(p, {"yt": {"kind": "format", "learned_from": 3,
                             "target_video_s": 540.0}})
    loaded = load_profiles(p)
    assert loaded["yt"]["kind"] == "format"
    assert loaded["yt"]["target_video_s"] == 540.0


# ---------- style-aware EDL ----------

def test_style_target_extends_max_length():
    from clip_lab.edl import _clip_bounds
    c = cfg(clip_max_s=45.0, clip_min_s=8.0)
    cand = Candidate(t0=100.0, t1=170.0, signal_score=1, category="hype",
                     style_target="insta_montage", window_from_llm=True)
    # without style: capped at 45
    t0a, t1a = _clip_bounds(cand, c, duration=1000)
    assert t1a - t0a <= 45.0 + 1e-6
    # with a learned 60s style: the style wins (60*1.25=75 >= 70s window)
    t0b, t1b = _clip_bounds(cand, c, duration=1000,
                            style_targets={"insta_montage": 60.0})
    assert t1b - t0b > 45.0
    assert t1b - t0b <= 90.0 + 1e-6


def test_llm_window_gets_no_extra_preroll():
    from clip_lab.edl import _clip_bounds
    c = cfg(funny_setup_preroll_s=6.0, clip_min_s=1.0, default_postroll_s=3.0)
    llm_win = Candidate(t0=100.0, t1=120.0, signal_score=1, category="funny",
                        window_from_llm=True)
    event_win = Candidate(t0=100.0, t1=120.0, signal_score=1, category="funny",
                          window_from_llm=False)
    t0_llm, _ = _clip_bounds(llm_win, c, duration=1000)
    t0_evt, _ = _clip_bounds(event_win, c, duration=1000)
    assert t0_llm == 100.0                                 # brain's setup respected
    assert t0_evt < 100.0                                  # category preroll applies


# ---------- language + hosts blocks ----------

def _prompts_for(cfg_obj):
    from clip_lab.editorial import run_editorial
    prompts = []
    def runner(prompt):
        prompts.append(prompt)
        return "[]" if "CANDIDATE WINDOWS" in prompt else "{}"
    run_editorial([Candidate(t0=1, t1=2, signal_score=1)], "log",
                  LLMClient(["x"], runner=runner), cfg_obj)
    return prompts


def test_auto_language_instruction_present():
    prompts = _prompts_for(cfg(use_llm=True))
    assert all("LANGUAGE THE STREAMERS SPEAK" in p for p in prompts)


def test_forced_language_instruction():
    prompts = _prompts_for(cfg(use_llm=True, output_language="German"))
    assert all("in German" in p for p in prompts)


def test_hosts_block_present_when_configured():
    prompts = _prompts_for(cfg(use_llm=True, hosts=["Max", "Tom"]))
    assert all("Max, Tom" in p for p in prompts)
    prompts2 = _prompts_for(cfg(use_llm=True))
    assert all("HOSTS:" not in p for p in prompts2)


# ---------- config audio_stream + top_k scaling ----------

def test_config_audio_stream_reaches_batch(tmp_path, monkeypatch):
    import clip_lab.pipeline as pipeline_mod
    captured = {}
    real_extract = pipeline_mod.ingest.extract_audio
    def spy(vod, out, *, sr=16000, audio_stream=None):
        captured["stream"] = audio_stream
        raise pipeline_mod.ingest.IngestError("stop here")
    monkeypatch.setattr(pipeline_mod.ingest, "extract_audio", spy)
    c = cfg(audio_stream="a:1")
    try:
        pipeline_mod.analyze(tmp_path / "v.mkv", c, tmp_path / "o",
                             log=lambda *a: None)
    except pipeline_mod.ingest.IngestError:
        pass
    assert captured["stream"] == "a:1"                     # config value applied


def test_top_k_scales_with_duration():
    from clip_lab.rank import rank_candidates
    cands = [Candidate(t0=i * 700.0, t1=i * 700.0 + 1, signal_score=i + 1)
             for i in range(30)]
    base = rank_candidates(list(cands), cfg(top_k=12, top_per_10min=4))
    scaled = rank_candidates(list(cands), cfg(top_k=12, top_per_10min=4),
                             top_k=24)
    assert len(base) == 12
    assert len(scaled) == 24
