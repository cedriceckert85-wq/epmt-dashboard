"""Regressions for the full-audit (Generalprobe) findings: first-run UX with a
blocked whisper-model download, CLI path validation, phantom reactions on quiet
audio, hostile titles, punchline-preserving excerpts, and the LLM cut window
actually being adopted."""
import json
import numpy as np
import pytest

from clip_lab.config import Config
from clip_lab.models import Candidate, TranscriptSegment
from clip_lab.cli import main


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ---------- whisper-model failure UX ----------

def test_transcribe_model_failure_is_friendly(monkeypatch, tmp_path):
    import clip_lab.transcribe as t
    fw = pytest.importorskip("faster_whisper")

    class Boom:
        def __init__(self, *a, **kw):
            raise ConnectionError("403 Forbidden")

    monkeypatch.setattr(fw, "WhisperModel", Boom)
    with pytest.raises(t.TranscribeError) as ei:
        t.transcribe(tmp_path / "x.wav", cfg())
    msg = str(ei.value)
    assert "--transcript" in msg          # escape hatch mentioned
    assert "internet" in msg.lower()      # cause explained


def test_style_transcriber_model_failure_returns_none(monkeypatch):
    import clip_lab.style as style
    fw = pytest.importorskip("faster_whisper")

    class Boom:
        def __init__(self, *a, **kw):
            raise ConnectionError("403 Forbidden")

    monkeypatch.setattr(fw, "WhisperModel", Boom)
    assert style._make_transcriber(cfg()) is None   # learn degrades, not dies


def test_cli_main_renders_operational_errors(monkeypatch, capsys, tmp_path):
    # a TranscribeError bubbling out of analyze must become a message, not a
    # traceback (exit 1)
    import clip_lab.cli as cli
    from clip_lab.transcribe import TranscribeError

    def boom(*a, **kw):
        raise TranscribeError("whisper model could not be loaded — pass --transcript")

    monkeypatch.setattr(cli, "analyze", boom)
    vod = tmp_path / "v.mkv"
    vod.write_bytes(b"x")
    rc = main(["analyze", str(vod), "--out", str(tmp_path / "o")])
    assert rc == 1
    assert "ERROR:" in capsys.readouterr().err


# ---------- CLI path validation ----------

def test_analyze_missing_transcript_friendly(tmp_path, capsys):
    rc = main(["analyze", "whatever.mkv", "--transcript", str(tmp_path / "no.json")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_analyze_missing_events_friendly(tmp_path, capsys):
    t = tmp_path / "t.json"
    t.write_text('{"segments": []}', encoding="utf-8")
    rc = main(["analyze", "whatever.mkv", "--transcript", str(t),
               "--events", str(tmp_path / "no.csv")])
    assert rc == 2
    assert "events file not found" in capsys.readouterr().err


def test_cut_missing_plan_friendly(tmp_path, capsys):
    vod = tmp_path / "v.mkv"
    vod.write_bytes(b"x")
    assert main(["cut", str(vod), str(tmp_path / "no.json")]) == 2
    assert "plan file not found" in capsys.readouterr().err


def test_cut_invalid_plan_friendly(tmp_path, capsys):
    vod = tmp_path / "v.mkv"
    vod.write_bytes(b"x")
    plan = tmp_path / "p.json"
    plan.write_text('{"not_clips": []}', encoding="utf-8")
    assert main(["cut", str(vod), str(plan)]) == 2
    assert "not a valid edit plan" in capsys.readouterr().err


def test_cut_missing_vod_friendly(tmp_path, capsys):
    plan = tmp_path / "p.json"
    plan.write_text('{"clips": []}', encoding="utf-8")
    assert main(["cut", str(tmp_path / "no.mkv"), str(plan)]) == 2


def test_batch_nonexistent_folder_message(tmp_path, capsys):
    assert main(["batch", str(tmp_path / "nope")]) == 2
    assert "does not exist" in capsys.readouterr().err


# ---------- phantom reactions on quiet audio ----------

def test_quiet_constant_audio_yields_no_reactions():
    from clip_lab.reactions import detect_reactions
    sr = 16000
    t = np.arange(sr * 30) / sr
    quiet = (0.0018 * np.sin(2 * np.pi * 440 * t)).astype("float32")  # ~-55 dBFS
    assert detect_reactions(quiet, sr) == []


def test_loud_bursts_still_detected_after_floor():
    from clip_lab.reactions import detect_reactions
    rng = np.random.default_rng(0)
    sr = 16000
    x = rng.standard_normal(sr * 30).astype("float32") * 0.02
    a = int(10.0 * sr)
    x[a:a + sr // 2] += rng.standard_normal(sr // 2).astype("float32") * 0.7
    evs = detect_reactions(np.clip(x, -1, 1), sr, prominence=0.4)
    assert any(abs(e.t - 10.0) < 1.5 for e in evs)


# ---------- hostile titles ----------

def test_nonstring_title_cannot_crash_the_sheet(tmp_path):
    from clip_lab.editorial import _moment_fields
    assert _moment_fields({"title": 42})["title"] is None
    assert _moment_fields({"title": "a\nmulti\nline"})["title"] == "a multi line"
    assert len(_moment_fields({"title": "x" * 500})["title"]) == 120


# ---------- excerpt keeps the punchline ----------

def test_excerpt_keeps_head_and_tail():
    from clip_lab.timeline import transcript_excerpt
    segs = [TranscriptSegment(t0=float(i), t1=float(i) + 0.9,
                              text=f"filler sentence number {i}")
            for i in range(60)]
    segs.append(TranscriptSegment(t0=60.0, t1=61.0, text="THE_PUNCHLINE_MARKER"))
    ex = transcript_excerpt(segs, 0, 62, max_chars=400)
    assert "filler sentence number 0" in ex        # head kept
    assert "THE_PUNCHLINE_MARKER" in ex            # tail (punchline) kept
    assert len(ex) <= 410


# ---------- LLM cut window is adopted ----------

def test_matched_candidate_adopts_llm_window():
    from clip_lab.editorial import _apply_moments
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    out = _apply_moments(cands, [{"t0": 138.0, "t1": 165.0,
                                  "semantic_score": 8}], cfg())
    assert out[0].t0 == 138.0 and out[0].t1 == 165.0   # setup intent kept


# ---------- style: 0 cuts/min is a real pace ----------

def test_zero_cutrate_becomes_uncut_pace():
    from clip_lab.style import _mechanical_profile
    prof = _mechanical_profile([{"duration_s": 45.0, "cuts_per_min": 0.0},
                                {"duration_s": 46.0, "cuts_per_min": 0.0}])
    assert "uncut" in prof["pace"]


def test_learn_has_no_llm_flag():
    from clip_lab.cli import build_parser
    args = build_parser().parse_args(["learn", "--no-llm"])
    assert args.no_llm is True


# ---------- config: broken toml warns ----------

def test_broken_config_toml_warns(tmp_path, capsys):
    (tmp_path / "config.toml").write_text("[[[broken", encoding="utf-8")
    c = Config.load(tmp_path)
    assert c.whisper_model == Config().whisper_model
    assert "WARNING" in capsys.readouterr().err
