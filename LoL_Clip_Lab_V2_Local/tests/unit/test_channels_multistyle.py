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
    assert "[insta]" in block and "[yt]" in block and "[uncut]" in block
    assert _channels_block(cfg(channels=[])) == ""


def test_tags_flow_through_editorial():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]

    def runner(prompt):
        if "CANDIDATE WINDOWS" in prompt:
            return json.dumps([{"t0": 90, "t1": 110, "semantic_score": 8,
                                "style": "montage", "channels": ["insta", "yt"]}])
        return "{}"

    out, _, _ = run_editorial(cands, "log", LLMClient(["x"], runner=runner),
                              cfg(), style_names=("montage",))
    assert out[0].style_target == "montage"
    assert out[0].channels == ["insta", "yt"]


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
    assert penta.channels == ["insta", "yt", "uncut"]


# ---------- nested channel/style folders ----------

def test_nested_folders_become_channel_styles(tmp_path, monkeypatch):
    # references/insta/funny -> insta_funny, insta/montage -> insta_montage,
    # flat yt/ stays yt — both levels coexist
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr("clip_lab.style._make_transcriber", lambda c: None)
    (tmp_path / "insta" / "funny").mkdir(parents=True)
    (tmp_path / "insta" / "montage").mkdir(parents=True)
    (tmp_path / "yt").mkdir()
    (tmp_path / "insta" / "funny" / "a.mp4").write_bytes(b"x")
    (tmp_path / "insta" / "montage" / "b.mp4").write_bytes(b"x")
    (tmp_path / "yt" / "c.mp4").write_bytes(b"x")
    profiles, _ = learn_styles(tmp_path, cfg(), None, run=_fake_run())
    assert set(profiles) == {"insta_funny", "insta_montage", "yt"}


def test_channel_folder_with_direct_videos_and_subfolders(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr("clip_lab.style._make_transcriber", lambda c: None)
    (tmp_path / "insta" / "funny").mkdir(parents=True)
    (tmp_path / "insta" / "direct.mp4").write_bytes(b"x")
    (tmp_path / "insta" / "funny" / "a.mp4").write_bytes(b"x")
    profiles, _ = learn_styles(tmp_path, cfg(), None, run=_fake_run())
    assert set(profiles) == {"insta", "insta_funny"}


def test_style_prefix_implies_channel():
    # a clip cut as insta_funny obviously serves insta, even if the LLM
    # forgot to tag the channel
    f = _moment_fields({"style": "insta_funny", "channels": ["yt"]},
                       style_names=("insta_funny",),
                       channel_names=("insta", "yt", "uncut"))
    assert f["style_target"] == "insta_funny"
    assert f["channels"][0] == "insta" and "yt" in f["channels"]
    # style exactly equal to a channel name works too
    g = _moment_fields({"style": "uncut", "channels": []},
                       style_names=("uncut",),
                       channel_names=("insta", "yt", "uncut"))
    assert g["channels"] == ["uncut"]
    # prefix that is NOT a channel adds nothing
    h = _moment_fields({"style": "cinematic_slow", "channels": []},
                       style_names=("cinematic_slow",),
                       channel_names=("insta", "yt", "uncut"))
    assert h["channels"] == []


def test_fetch_nested_style_path(tmp_path, monkeypatch):
    import clip_lab.util as util
    import subprocess as sp
    from clip_lab.cli import main
    monkeypatch.setattr(util, "which", lambda n: "/usr/bin/" + n)
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(sp, "run", fake_run)
    assert main(["fetch", "http://x", "--style", "insta/funny"]) == 0
    tmpl = calls[0][2]
    assert "insta" in tmpl and "funny" in tmpl and ".." not in tmpl


# ---------- hostile-input regressions (verification findings) ----------

def test_identical_point_windows_are_duplicates():
    # two zero-width takes at the same t must be ONE moment, not a spurious
    # discovery that burns a top_k slot
    from clip_lab.editorial import _apply_moments
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]
    moments = [{"t0": 100, "t1": 100, "semantic_score": 9, "title": "penta"},
               {"t0": 100, "t1": 100, "semantic_score": 8, "title": "dup"}]
    out = _apply_moments(cands, moments, cfg())
    assert len(out) == 1


def test_edge_adjacent_real_windows_do_not_match():
    # B's duplicate take must not blend into the NEIGHBORING clip
    from clip_lab.editorial import _blend_second_opinion
    x = Candidate(t0=10.0, t1=20.0, signal_score=1, semantic_score=8.0,
                  editorial_source="llm", why="x")
    y = Candidate(t0=20.0, t1=30.0, signal_score=1, semantic_score=2.0,
                  editorial_source="llm", why="y")
    _blend_second_opinion([x, y], [{"t0": 10, "t1": 20, "semantic_score": 9},
                                   {"t0": 10, "t1": 20, "semantic_score": 9}])
    assert y.semantic_score == 2.0                 # neighbor untouched
    assert "[2nd opinion" not in y.why


def test_scalar_channels_config_does_not_crash():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]
    def runner(prompt):
        return "[]" if "CANDIDATE WINDOWS" in prompt else "{}"
    out, source, _ = run_editorial(cands, "log", LLMClient(["x"], runner=runner),
                                   cfg(channels=3))
    assert source == "llm"                          # no TypeError
    assert _channels_block(cfg(channels="shorts")) == ""


def test_styles_brief_keeps_every_style_name_under_budget():
    profiles = {f"style{i}": {"learned_from": 3, "target_clip_s": 20.0,
                              "pace": "p" * 150, "caption_style": "c" * 150,
                              "notes": "n" * 300,
                              "humor_style": ["dry humor trait"] * 3}
                for i in range(8)}
    brief = styles_brief(profiles, max_chars=2500)
    for name in profiles:
        assert f"[{name}]" in brief, name           # no style silently dropped


def test_category_is_sanitized_for_csv_and_filenames():
    f = _moment_fields({"category": 'funny,but "hype"/../evil'})
    assert "," not in f["category"] and "/" not in f["category"]
    assert f["category"] == "funnybuthypeevil"[:20]
    assert _moment_fields({"category": "///"})["category"] == "moment"


def test_style_folder_names_are_slugged(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_lab.style.which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr("clip_lab.style._make_transcriber", lambda c: None)
    (tmp_path / "my,funny style!").mkdir()
    (tmp_path / "my,funny style!" / "a.mp4").write_bytes(b"x")
    profiles, _ = learn_styles(tmp_path, cfg(), None, run=_fake_run())
    assert set(profiles) == {"my_funny_style"}      # CSV/prompt-safe slug


def test_chapter_at_zero_keeps_its_title(tmp_path):
    from clip_lab.editsheet import write_edit_sheet
    plan = [_item(1, 0.4, 12.0, "Cold Open", []),
            _item(2, 500.0, 520.0, "Later", [])]
    write_edit_sheet(plan, tmp_path, vod_name="v", meta={"duration": 1000})
    lines = (tmp_path / "chapters.txt").read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "00:00 Cold Open"            # no Intro stealing the slot
    assert lines[1] == "08:20 Later"


def test_chapter_second_collision_bumps_not_drops(tmp_path):
    from clip_lab.editsheet import write_edit_sheet
    plan = [_item(1, 100.2, 110.0, "First", []),
            _item(2, 100.9, 111.0, "Second", [])]
    write_edit_sheet(plan, tmp_path, vod_name="v", meta={"duration": 1000})
    txt = (tmp_path / "chapters.txt").read_text(encoding="utf-8")
    assert "First" in txt and "Second" in txt       # both titles survive


def test_fetch_style_is_slugged(tmp_path, monkeypatch):
    import clip_lab.util as util
    import subprocess as sp
    from clip_lab.cli import main
    monkeypatch.setattr(util, "which", lambda n: "/usr/bin/" + n)
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(sp, "run", fake_run)
    rc = main(["fetch", "http://x", "--style", "My Funny"])
    assert rc == 0
    tmpl = calls[0][2]
    assert "my_funny" in tmpl                        # learner-compatible slug
    calls.clear()
    # a traversal attempt is REJECTED outright (".." slugs to empty)
    assert main(["fetch", "http://x", "--style", "../evil"]) == 2
    assert not calls


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