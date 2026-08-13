"""F7: Stil-Lernen aus Referenz-Clips."""

from __future__ import annotations

import json

import pytest

from cliplab.config import Config
from cliplab.styles import (
    STYLE_MARKER,
    StyleProfile,
    ensure_example_structure,
    learn_styles,
    load_profile,
    save_profile,
    scan_references,
    style_channel,
)
from tests.conftest import FakeRunner


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake video")
    return path


class TestScan:
    def test_two_levels(self, tmp_path):
        touch(tmp_path / "refs" / "insta" / "funny" / "a.mp4")
        touch(tmp_path / "refs" / "insta" / "funny" / "b.mkv")
        touch(tmp_path / "refs" / "insta" / "montage" / "c.mp4")
        groups = scan_references(tmp_path / "refs")
        assert set(groups) == {"insta_funny", "insta_montage"}
        assert len(groups["insta_funny"]) == 2

    def test_level_one_alone(self, tmp_path):
        touch(tmp_path / "refs" / "yt" / "video.mp4")
        groups = scan_references(tmp_path / "refs")
        assert set(groups) == {"yt"}

    def test_root_videos(self, tmp_path):
        touch(tmp_path / "refs" / "clip.mp4")
        groups = scan_references(tmp_path / "refs")
        assert set(groups) == {"default"}

    def test_slug_from_folder_names(self, tmp_path):
        touch(tmp_path / "refs" / "Mein Insta!" / "Funny Stuff" / "a.mp4")
        groups = scan_references(tmp_path / "refs")
        assert set(groups) == {"mein_insta_funny_stuff"}

    def test_non_video_ignored(self, tmp_path):
        touch(tmp_path / "refs" / "insta" / "funny" / "notizen.txt")
        groups = scan_references(tmp_path / "refs")
        assert groups == {}

    def test_missing_dir(self, tmp_path):
        assert scan_references(tmp_path / "nix") == {}


class TestClassification:
    def _learn(self, tmp_path, cfg, durations_by_file, rates=None, runner=None):
        files = {}
        for name, dur in durations_by_file.items():
            files[str(touch(tmp_path / "refs" / name))] = dur
        return learn_styles(
            tmp_path / "refs",
            cfg,
            probe_duration=lambda p: files.get(str(p)),
            scene_rate=(lambda p, d: rates.get(p.name) if rates else None),
            runner=runner,
        )

    def test_short_clips_become_cut_style(self, tmp_path, cfg):
        profile, report = self._learn(
            tmp_path, cfg,
            {"insta/funny/a.mp4": 35.0, "insta/funny/b.mp4": 45.0, "insta/funny/c.mp4": 40.0},
        )
        assert "insta_funny" in profile.cuts
        assert profile.cuts["insta_funny"]["ideal_len_s"] == 40.0  # Median
        assert profile.formats == {}

    def test_long_videos_become_format_profile(self, tmp_path, cfg):
        profile, report = self._learn(tmp_path, cfg, {"yt/v1.mp4": 600.0, "yt/v2.mp4": 660.0})
        assert "yt" in profile.formats
        assert profile.formats["yt"]["target_runtime_s"] == 630.0
        # Ganze Videos NIE als Clip-Schnittstil
        assert profile.cuts == {}
        assert any("Kein Clip-Schnittstil" in r for r in report)

    def test_single_10min_video_never_cut_style(self, tmp_path, cfg):
        profile, _ = self._learn(tmp_path, cfg, {"yt/video.mp4": 600.0})
        assert profile.cuts == {}
        assert "yt" in profile.formats

    def test_median_decides_mixed_group(self, tmp_path, cfg):
        profile, _ = self._learn(
            tmp_path, cfg,
            {"insta/a.mp4": 30.0, "insta/b.mp4": 40.0, "insta/c.mp4": 500.0},
        )
        assert "insta" in profile.cuts  # Median 40 <= 120

    def test_zero_cuts_per_min_is_real_measurement(self, tmp_path, cfg):
        profile, _ = self._learn(
            tmp_path, cfg, {"insta/funny/a.mp4": 50.0}, rates={"a.mp4": 0.0}
        )
        entry = profile.cuts["insta_funny"]
        assert entry["cuts_per_min"] == 0.0
        assert "ungeschnittene Takes" in entry["notes"]

    def test_nonfinite_duration_discarded(self, tmp_path, cfg):
        profile, report = self._learn(
            tmp_path, cfg,
            {"insta/a.mp4": float("inf"), "insta/b.mp4": -5.0, "insta/c.mp4": 40.0},
        )
        assert profile.cuts["insta"]["sample_count"] == 1
        assert any("uebersprungen" in r for r in report)

    def test_all_unmeasurable_style_skipped(self, tmp_path, cfg):
        profile, report = self._learn(tmp_path, cfg, {"insta/a.mp4": None})
        assert profile.is_empty()

    def test_probe_exception_survives(self, tmp_path, cfg):
        touch(tmp_path / "refs" / "insta" / "a.mp4")

        def boom(p):
            raise RuntimeError("ffprobe kaputt")

        profile, report = learn_styles(tmp_path / "refs", cfg, probe_duration=boom)
        assert profile.is_empty()

    def test_no_whisper_learning_continues(self, tmp_path, cfg):
        # transcribe_sample=None: ohne Text weiterlernen, nicht abbrechen
        profile, _ = self._learn(tmp_path, cfg, {"insta/funny/a.mp4": 40.0})
        assert "insta_funny" in profile.cuts

    def test_llm_distillation_used(self, tmp_path, cfg):
        runner = FakeRunner(
            by_marker={
                STYLE_MARKER: json.dumps(
                    {"notes": "Trockener Humor, Punch nach vorn", "caption_style": "GROSS"}
                )
            }
        )
        profile, _ = self._learn(
            tmp_path, cfg, {"insta/funny/a.mp4": 40.0}, runner=runner
        )
        assert profile.cuts["insta_funny"]["notes"] == "Trockener Humor, Punch nach vorn"
        assert profile.cuts["insta_funny"]["caption_style"] == "GROSS"

    def test_llm_garbage_mechanical_fallback(self, tmp_path, cfg):
        runner = FakeRunner(by_marker={STYLE_MARKER: "kein json"})
        profile, _ = self._learn(tmp_path, cfg, {"insta/funny/a.mp4": 40.0}, runner=runner)
        assert "Mechanisch gelernt" in profile.cuts["insta_funny"]["notes"]

    def test_channel_implied_from_style_name(self, tmp_path, cfg):
        profile, _ = self._learn(tmp_path, cfg, {"insta/funny/a.mp4": 40.0})
        assert profile.cuts["insta_funny"]["channel"] == "insta"

    def test_empty_folder_report(self, tmp_path, cfg):
        (tmp_path / "refs").mkdir()
        profile, report = learn_styles(tmp_path / "refs", cfg, probe_duration=lambda p: 1.0)
        assert profile.is_empty() and any("Keine Referenz" in r for r in report)


class TestProfileIO:
    def test_roundtrip(self, tmp_path):
        prof = StyleProfile()
        prof.cuts["insta_funny"] = {
            "ideal_len_s": 40.0, "cuts_per_min": 10.0, "notes": "n",
            "caption_style": "c", "channel": "insta", "sample_count": 3,
        }
        prof.formats["yt"] = {
            "target_runtime_s": 600.0, "channel": "yt", "sample_count": 2, "notes": "",
        }
        p = tmp_path / "profile.json"
        save_profile(p, prof)
        loaded = load_profile(p)
        assert loaded.cuts["insta_funny"]["ideal_len_s"] == 40.0
        assert loaded.formats["yt"]["target_runtime_s"] == 600.0

    def test_missing_file_empty(self, tmp_path):
        assert load_profile(tmp_path / "nix.json").is_empty()

    def test_corrupt_json_empty(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text("{kaputt", encoding="utf-8")
        assert load_profile(p).is_empty()

    def test_wrong_version_empty(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text('{"version": 99, "cuts": {}}', encoding="utf-8")
        assert load_profile(p).is_empty()

    def test_missing_version_empty(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text('{"cuts": {}}', encoding="utf-8")
        assert load_profile(p).is_empty()

    def test_hostile_entries_sanitized(self, tmp_path):
        p = tmp_path / "p.json"
        p.write_text(
            json.dumps(
                {
                    "version": 1,
                    "cuts": {
                        "ok": {"ideal_len_s": 40},
                        "inf": {"ideal_len_s": float("1e999")},
                        "neg": {"ideal_len_s": -5},
                        "muell": "string",
                    },
                    "formats": {"f": {"target_runtime_s": "keine zahl"}},
                }
            ).replace("Infinity", "Infinity"),
            encoding="utf-8",
        )
        loaded = load_profile(p)
        assert set(loaded.cuts) == {"ok"}
        assert loaded.formats == {}

    def test_format_runtime_for_channel(self):
        prof = StyleProfile()
        prof.formats["yt"] = {"target_runtime_s": 600.0, "channel": "yt", "sample_count": 1, "notes": ""}
        assert prof.format_runtime_for_channel("yt") == 600.0
        assert prof.format_runtime_for_channel("insta") is None

    def test_cut_style_target_len(self):
        prof = StyleProfile()
        prof.cuts["s"] = {"ideal_len_s": 42.0}
        assert prof.cut_style_target_len("s") == 42.0
        assert prof.cut_style_target_len("nix") is None


class TestMisc:
    def test_style_channel_coherence(self):
        assert style_channel("insta_funny", ["insta", "yt"]) == "insta"
        assert style_channel("insta", ["insta", "yt"]) == "insta"
        assert style_channel("default", ["insta", "yt"]) == ""
        # kein Prefix-Fehlmatch: "instagram_x" gehoert nicht zu "insta"
        assert style_channel("instagram_x", ["insta", "yt"]) == ""

    def test_example_structure_created_once(self, tmp_path, cfg):
        ref = tmp_path / "references"
        assert ensure_example_structure(ref, cfg) is True
        assert (ref / "insta" / "funny").is_dir()
        assert (ref / "LIES_MICH.txt").is_file()
        assert ensure_example_structure(ref, cfg) is False  # idempotent
