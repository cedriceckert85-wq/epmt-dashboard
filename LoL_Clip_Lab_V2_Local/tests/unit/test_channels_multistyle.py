"""Multi-style references (one style per subfolder) + channel routing: the
content decides per moment which STYLE it is cut in and which CHANNELS
(shorts / main / uncut) it serves; the sheet ends with per-channel plans and
chapters.txt for the uncut upload."""
import json
from pathlib import Path
from types import SimpleNamespace

from clip_lab.config import Config
from clip_lab.editorial import run_editorial, _channels_block, _moment_fields
from clip_lab.llm_client import LLMClient
from clip_lab.models import Candidate, EditPlanItem
from clip_lab.style import (learn_styles, load_profiles, save_profile,
                            save_profiles, styles_brief)

ROOT = Path(__file__).resolve().parents[2]


def cfg(**kw):
    c = Config()
    c.use_llm = True
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ---------- multi-style learning ----------

def _fake_run(dur="25.0"):
    def run(cmd, **kw):
        if cmd[0] == "ffprobe":
            return SimpleNamespace(stdout=dur, stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    return run


def test_subfolders_become_named_styles(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr("clip_lab.style._make_transcriber", lambda c: None)
    (tmp_path / "funny").mkdir()
    (tmp_path / "montage").mkdir()
    (tmp_path / "funny" / "a.mp4").write_bytes(b"x")
    (tmp_path / "montage" / "b.mp4").write_bytes(b"x")
    (tmp_path / "root.mp4").write_bytes(b"x")

    prompts = []
    def runner(p):
        prompts.append(p)
        return '{"target_clip_s": 20}'

    profiles, fps = learn_styles(tmp_path, cfg(), LLMClient(["x"], runner=runner),
                                 run=_fake_run())
    assert set(profiles) == {"default", "funny", "montage"}
    assert all(p["learned_from"] == 1 for p in profiles.values())
    # each style prompt names its style
    assert any("'funny' style" in p for p in prompts)
    assert any("'montage' style" in p for p in prompts)


def test_profiles_roundtrip_v2(tmp_path):
    path = tmp_path / "s.json"
    save_profiles(path, {"funny": {"learned_from": 3, "target_clip_s": 18.0},
                         "montage": {"learned_from": 5, "target_clip_s": 40.0}})
    loaded = load_profiles(path)
    assert set(loaded) == {"funny", "montage"}
    assert loaded["montage"]["target_clip_s"] == 40.0


def test_v1_file_loads_as_default_style(tmp_path):
    path = tmp_path / "s.json"
    save_profile(path, {"learned_from": 2, "target_clip_s": 25.0})
    loaded = load_profiles(path)
    assert set(loaded) == {"default"}
    assert loaded["default"]["target_clip_s"] == 25.0


def test_load_profiles_corrupt(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{{{nope", encoding="utf-8")
    assert load_profiles(p) == {}
    assert load_profiles(tmp_path / "missing.json") == {}


def test_styles_brief_lists_names_and_instruction():
    brief = styles_brief({"funny": {"learned_from": 3, "target_clip_s": 18.0},
                          "montage": {"learned_from": 5, "pace": "fast"}})
    assert '"style": "<name>"' in brief
    assert "[funny]" in brief and "[montage]" in brief
    assert "18.0s" in brief


def test_styles_brief_single_default_reads_like_classic():
    brief = styles_brief({"default": {"learned_from": 4, "target_clip_s": 22.0}})
    assert brief.startswith("STYLE GUIDE (learned from 4")


# ---------- per-moment style + channel tagging ----------

def test_moment_style_validated_against_learned_names():
    ok = _moment_fields({"style": "Montage"}, style_names=("funny", "montage"))
    assert ok["style_target"] == "montage"
    bad = _moment_fields({"style": "invented"}, style_names=("funny", "montage"))
    assert bad["style_target"] is None
    none = _moment_fields({"style": "funny"})           # nothing learned
    assert none["style_target"] is None


def test_moment_channels_validated_against_config():
    f = _moment_fields({"channels": ["Shorts", "main", "tiktok", 42, "shorts"]},
                       channel_names=("shorts", "main", "uncut"))
    assert f["channels"] == ["shorts", "main"]          # known, deduped, ordered
    assert _moment_fields({"channels": "shorts"},
                          channel_names=("shorts",))["channels"] == []


def test_channels_block_from_config():
    block = _channels_block(cfg())
    assert "[shorts]" in block and "[main]" in block and "[uncut]" in block
    assert _channels_block(cfg(channels=[])) == ""


def test_tags_flow_through_editorial():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]

    def runner(prompt):
        if "CANDIDATE WINDOWS" in prompt:
            return json.dumps([{"t0": 90, "t1": 110, "semantic_score": 8,
                                "style": "montage", "channels": ["shorts", "main"]}])
        return "{}"

    out, _, _ = run_editorial(cands, "log", LLMClient(["x"], runner=runner),
                              cfg(), style_names=("montage",))
    assert out[0].style_target == "montage"
    assert out[0].channels == ["shorts", "main"]


# ---------- sheet: channel plans + chapters ----------

def _item(rank, t0, t1, title, channels, style=None):
    return EditPlanItem(rank=rank, clip_t0=t0, clip_t1=t1, category="hype",
                        title=title, why="w", punchline_t=None,
                        final_score=1.0 - rank * 0.1, channels=channels,
                        style_target=style)


def test_sheet_shows_style_channels_and_plans(tmp_path):
    from clip_lab.editsheet import write_edit_sheet
    plan = [_item(1, 100, 130, "Big Penta", ["shorts", "main"], style="montage"),
            _item(2, 500, 580, "Long Talk", ["main"])]
    write_edit_sheet(plan, tmp_path, vod_name="v.mkv", meta={"duration": 1000})
    md = (tmp_path / "edit_sheet.md").read_text(encoding="utf-8")
    assert "**Cut as:** montage-style" in md
    assert "**Channels:** shorts, main" in md
    assert "## 📺 Channel plans" in md
    assert "### shorts" in md and "### main" in md
    assert "⚠️ over 60s" not in md.split("### shorts")[1].split("###")[0]


def test_shorts_over_60s_warned(tmp_path):
    from clip_lab.editsheet import write_edit_sheet
    plan = [_item(1, 100, 190, "Way Too Long", ["shorts"])]
    write_edit_sheet(plan, tmp_path, vod_name="v.mkv", meta={"duration": 1000})
    md = (tmp_path / "edit_sheet.md").read_text(encoding="utf-8")
    assert "⚠️ over 60s" in md


def test_chapters_txt_ascending_from_zero(tmp_path):
    from clip_lab.editsheet import write_edit_sheet
    plan = [_item(1, 1332.0, 1350.0, "Penta", ["uncut"]),
            _item(2, 150.0, 165.0, "First Blood", []),
            _item(3, 3700.0, 3720.0, "Late Game", [])]
    write_edit_sheet(plan, tmp_path, vod_name="v.mkv", meta={"duration": 4000})
    lines = (tmp_path / "chapters.txt").read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "00:00 Intro"
    assert lines[1] == "02:30 First Blood"
    assert lines[2] == "22:12 Penta"
    assert lines[3] == "1:01:40 Late Game"


def test_csv_has_style_and_channels_columns(tmp_path):
    from clip_lab.editsheet import write_edit_sheet
    plan = [_item(1, 100, 130, "Clip", ["shorts", "main"], style="funny")]
    write_edit_sheet(plan, tmp_path, vod_name="v.mkv", meta={"duration": 1000})
    csv = (tmp_path / "clips.csv").read_text(encoding="utf-8")
    header, row = csv.strip().splitlines()
    assert header.endswith(",style,channels")
    assert row.endswith(",funny,shorts+main")


# ---------- e2e: selftest fixtures produce channel plans ----------

def test_demo_pipeline_produces_channel_plans(tmp_path):
    from clip_lab._demo import demo_llm
    from clip_lab.pipeline import analyze
    c = Config()
    c.use_llm = True
    plan, meta = analyze(str(ROOT / "samples" / "sample_vod.mkv"), c, tmp_path,
                         transcript_path=ROOT / "samples" / "fixture_transcript.json",
                         events_path=ROOT / "samples" / "fixture_events.json",
                         llm=demo_llm(), log=lambda *a: None)
    md = (tmp_path / "edit_sheet.md").read_text(encoding="utf-8")
    assert "## 📺 Channel plans" in md
    assert (tmp_path / "chapters.txt").exists()
    penta = [p for p in plan if "PENTAKILL" in (p.title or "")][0]
    assert penta.channels == ["shorts", "main", "uncut"]


# ---------- selftest never builds the second brain (determinism fix) ----------

def test_selftest_never_constructs_codex_client(tmp_path, monkeypatch):
    import clip_lab.pipeline as pipeline_mod
    from clip_lab.cli import main

    real = pipeline_mod.LLMClient

    class Bomb(real):
        def __init__(self, cmd, *a, **kw):
            if cmd and cmd[0] == "codex":
                raise AssertionError("selftest must not build the codex client")
            super().__init__(cmd, *a, **kw)

    monkeypatch.setattr(pipeline_mod, "LLMClient", Bomb)
    assert main(["selftest", "--out", str(tmp_path / "o")]) == 0