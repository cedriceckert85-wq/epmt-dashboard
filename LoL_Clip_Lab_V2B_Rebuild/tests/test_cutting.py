"""F13 cut: Plan-Validierung, Stumm-Fehlschlag, Kanaele, Encoder-Wahl."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cliplab.config import Config
from cliplab.cutting import cut_from_plan, load_plan
from cliplab.errors import ClipLabError, MissingInputError
from cliplab.media import make_clip_filename, pick_encoder_args
from tests.conftest import FakeProc

quiet = lambda s: None  # noqa: E731


def write_plan(tmp_path, clips, channels=None):
    plan = {"version": 1, "clips": clips}
    if channels is not None:
        plan["channels"] = channels
    p = tmp_path / "edit_plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


def fake_which(name):
    return f"/usr/bin/{name}"


def make_run(records, duration=100.0, create_output=True):
    def _run(argv, **kw):
        records.append(list(argv))
        exe = Path(argv[0]).name
        if exe == "ffprobe":
            return FakeProc(0, stdout=f"{duration}\n")
        if exe == "ffmpeg":
            if "-encoders" in argv:
                return FakeProc(0, stdout=" V....D libx264\n V....D h264_amf\n")
            out = Path(argv[-1])
            if create_output:
                out.write_bytes(b"videodata")
            return FakeProc(0)
        return FakeProc(1)

    return _run


class TestLoadPlan:
    def test_missing_file(self, tmp_path):
        with pytest.raises(MissingInputError):
            load_plan(tmp_path / "nix.json")

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text("{kaputt", encoding="utf-8")
        with pytest.raises(ClipLabError):
            load_plan(p)

    def test_wrong_shape(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text('{"keine_clips": true}', encoding="utf-8")
        with pytest.raises(ClipLabError):
            load_plan(p)

    def test_valid(self, tmp_path):
        p = write_plan(tmp_path, [{"t0": 1, "t1": 5, "title": "a"}])
        assert load_plan(p)["clips"]


class TestCut:
    def test_missing_vod(self, tmp_path, cfg):
        plan = write_plan(tmp_path, [{"t0": 1, "t1": 5}])
        with pytest.raises(MissingInputError):
            cut_from_plan(tmp_path / "nix.mkv", plan, cfg, log=quiet)

    def test_no_valid_clips_error(self, tmp_path, cfg):
        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = write_plan(tmp_path, [{"t0": "kaputt"}, {"t1": 5}])
        with pytest.raises(ClipLabError):
            cut_from_plan(vod, plan, cfg, log=quiet, which=fake_which, run_fn=make_run([]))

    def test_range_outside_video_error_not_empty_file(self, tmp_path, cfg):
        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = write_plan(tmp_path, [{"t0": 500, "t1": 540, "title": "zu spaet", "rank": 1}])
        records = []
        ok, notes, errors = cut_from_plan(
            vod, plan, cfg, log=quiet, which=fake_which,
            run_fn=make_run(records, duration=100.0),
        )
        assert ok == 0
        # Range ausserhalb = FEHLER (nicht bloss Hinweis)
        assert any("100" in e or "ausserhalb" in e for e in errors)
        # ffmpeg wurde fuer diesen Clip gar nicht erst aufgerufen
        assert not any("-ss" in r for r in records)

    def test_truncated_range_honest_note(self, tmp_path, cfg):
        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = write_plan(tmp_path, [{"t0": 90, "t1": 150, "title": "lang", "rank": 1}])
        records = []
        ok, notes, errors = cut_from_plan(
            vod, plan, cfg, log=quiet, which=fake_which,
            run_fn=make_run(records, duration=100.0),
        )
        assert ok >= 1
        assert any("gekuerzt" in n for n in notes)
        assert errors == []  # gekuerzt ist ein Hinweis, kein Fehler

    def test_channel_names_in_filenames(self, tmp_path, cfg):
        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = write_plan(
            tmp_path,
            [{"t0": 10, "t1": 20, "title": "Toller Clip", "rank": 1,
              "category": "funny", "channels": ["insta", "yt"]}],
            channels=[
                {"name": "insta", "kind": "clips", "vertical": True},
                {"name": "yt", "kind": "clips", "vertical": False},
            ],
        )
        records = []
        ok, _, _ = cut_from_plan(
            vod, plan, cfg, out_dir=tmp_path / "clips", log=quiet,
            which=fake_which, run_fn=make_run(records),
        )
        assert ok == 2
        names = [Path(r[-1]).name for r in records if "-ss" in r]
        assert any(n.endswith("_insta.mp4") for n in names)
        assert any(n.endswith("_yt.mp4") for n in names)

    def test_vertical_channel_gets_crop(self, tmp_path, cfg):
        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = write_plan(
            tmp_path,
            [{"t0": 10, "t1": 20, "title": "x", "rank": 1, "channels": ["insta"]}],
            channels=[{"name": "insta", "kind": "clips", "vertical": True}],
        )
        records = []
        cut_from_plan(vod, plan, cfg, log=quiet, which=fake_which, run_fn=make_run(records))
        cut_call = next(r for r in records if "-ss" in r)
        assert any("crop=" in a and "9/16" in a for a in cut_call)

    def test_full_channel_not_cut(self, tmp_path, cfg):
        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = write_plan(
            tmp_path,
            [{"t0": 10, "t1": 20, "title": "x", "rank": 1, "channels": ["uncut"]}],
            channels=[{"name": "uncut", "kind": "full", "vertical": False}],
        )
        records = []
        ok, _, _ = cut_from_plan(vod, plan, cfg, log=quiet, which=fake_which, run_fn=make_run(records))
        cut_call = next(r for r in records if "-ss" in r)
        assert ok == 1  # eine Datei OHNE Kanal-Suffix
        assert not Path(cut_call[-1]).name.endswith("_uncut.mp4")

    def test_broken_entries_skipped_with_note(self, tmp_path, cfg):
        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = write_plan(
            tmp_path,
            [{"t0": "x", "t1": 5}, {"t0": 10, "t1": 20, "title": "ok", "rank": 1}],
        )
        ok, notes, errors = cut_from_plan(
            vod, plan, cfg, log=quiet, which=fake_which, run_fn=make_run([])
        )
        assert ok == 1 and any("uebersprungen" in n for n in notes)


class TestEncoderChoice:
    def test_auto_prefers_amf_when_available(self):
        run = lambda a, **k: FakeProc(0, stdout=" V..... h264_amf  AMD\n V..... libx264\n")  # noqa: E731
        name, args = pick_encoder_args("auto", run_fn=run, which=fake_which)
        assert name == "h264_amf" and "h264_amf" in args

    def test_auto_falls_back_to_x264(self):
        run = lambda a, **k: FakeProc(0, stdout=" V..... libx264\n")  # noqa: E731
        name, args = pick_encoder_args("auto", run_fn=run, which=fake_which)
        assert name == "libx264"

    def test_explicit_amf(self):
        name, _ = pick_encoder_args("amf", which=fake_which)
        assert name == "h264_amf"

    def test_explicit_x264(self):
        name, _ = pick_encoder_args("x264", which=fake_which)
        assert name == "libx264"

    def test_unknown_encoder_rejected(self):
        with pytest.raises(ClipLabError):
            pick_encoder_args("wunder_gpu_encoder", which=fake_which)

    def test_no_ffmpeg_auto_x264(self):
        name, _ = pick_encoder_args("auto", which=lambda n: None)
        assert name == "libx264"

    def test_allowlist_is_amd_safe(self):
        # nur AMF oder x264 — nichts anderes existiert als Zweig
        for choice in ("auto", "amf", "x264", "h264_amf", "libx264"):
            name, _ = pick_encoder_args(choice, run_fn=lambda a, **k: FakeProc(0, stdout=""), which=fake_which)
            assert name in ("h264_amf", "libx264")


class TestFilenames:
    def test_channel_included(self):
        name = make_clip_filename(3, "funny", "Mein Titel!", "insta")
        assert name == "clip_03_funny_mein_titel_insta.mp4"

    def test_path_chars_neutralized(self):
        name = make_clip_filename(1, "../evil", "a/b\\c", "yt")
        assert "/" not in name and "\\" not in name and ".." not in name

    def test_no_channel(self):
        assert make_clip_filename(1, "funny", "t") == "clip_01_funny_t.mp4"
