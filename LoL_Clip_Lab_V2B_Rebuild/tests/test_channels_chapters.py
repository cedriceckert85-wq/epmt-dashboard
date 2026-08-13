"""F8: Kanal-Plaene (chronologisch) und YouTube-Kapitel."""

from __future__ import annotations

import pytest

from cliplab.channels import build_channel_plans, build_chapters, render_chapters
from cliplab.config import ChannelSpec, Config
from cliplab.planning import Clip
from cliplab.styles import StyleProfile


def clip(rank, t0, t1, channels=("insta",), title=None, style=""):
    return Clip(
        rank=rank, t0=t0, t1=t1, title=title or f"Clip {rank}", category="funny",
        final=1.0 - rank * 0.1, score=8, signal=1, style=style,
        channels=list(channels), punchline_t=-1, punchline_state="unknown", reason="",
    )


class TestPlans:
    def test_chronological_with_rank_per_line(self, cfg):
        clips = [clip(1, 3000, 3040), clip(2, 100, 140), clip(3, 1500, 1540)]
        plans = build_channel_plans(clips, cfg, None)
        insta = next(p for p in plans if p.spec.name == "insta")
        assert [e.t0 for e in insta.entries] == [100, 1500, 3000]  # chronologisch
        assert [e.rank for e in insta.entries] == [2, 3, 1]  # Rang pro Zeile

    def test_only_tagged_clips_in_plan(self, cfg):
        clips = [clip(1, 100, 140, channels=["yt"]), clip(2, 200, 240, channels=["insta"])]
        plans = build_channel_plans(clips, cfg, None)
        yt = next(p for p in plans if p.spec.name == "yt")
        assert len(yt.entries) == 1 and yt.entries[0].rank == 1

    def test_length_warning_over_max_s(self, cfg):
        clips = [clip(1, 100, 190)]  # 90s > insta max 60
        plans = build_channel_plans(clips, cfg, None)
        insta = next(p for p in plans if p.spec.name == "insta")
        assert "LAENGE" in insta.entries[0].warning

    def test_no_warning_within_max(self, cfg):
        clips = [clip(1, 100, 150)]
        plans = build_channel_plans(clips, cfg, None)
        insta = next(p for p in plans if p.spec.name == "insta")
        assert insta.entries[0].warning == ""

    def test_full_channel_no_entries(self, cfg):
        clips = [clip(1, 100, 140, channels=["insta", "uncut"])]
        plans = build_channel_plans(clips, cfg, None)
        uncut = next(p for p in plans if p.spec.name == "uncut")
        assert uncut.is_full and uncut.entries == []

    def test_format_runtime_attached(self, cfg):
        prof = StyleProfile()
        prof.formats["yt"] = {"target_runtime_s": 600.0, "channel": "yt", "sample_count": 1, "notes": ""}
        plans = build_channel_plans([], cfg, prof)
        yt = next(p for p in plans if p.spec.name == "yt")
        assert yt.format_runtime_s == 600.0

    def test_renamed_channels_followed(self):
        cfg = Config()
        cfg.channels = [
            ChannelSpec(name="shorts", max_s=45),
            ChannelSpec(name="archiv", kind="full"),
        ]
        clips = [clip(1, 100, 160, channels=["shorts"])]
        plans = build_channel_plans(clips, cfg, None)
        assert [p.spec.name for p in plans] == ["shorts", "archiv"]
        assert plans[0].entries and "45" in plans[0].entries[0].warning


class TestChapters:
    def test_first_chapter_exactly_zero(self):
        chapters = build_chapters([clip(1, 500, 540)], 3600)
        assert chapters[0][0] == 0.0
        text = render_chapters(chapters)
        assert text.startswith("00:00 ")

    def test_early_first_clip_becomes_opener(self):
        # Clip bei t=4 (< 10s): wird SELBST der Opener bei 00:00
        chapters = build_chapters([clip(1, 4, 40, title="Frueher Clip")], 3600)
        assert chapters[0] == (0.0, "Frueher Clip")
        assert len([c for c in chapters if c[1] == "Frueher Clip"]) == 1

    def test_late_clips_get_start_opener(self):
        chapters = build_chapters([clip(1, 500, 540, title="Spaeter")], 3600)
        assert chapters[0][1] == "Start"
        assert chapters[1] == (500.0, "Spaeter")

    def test_ascending(self):
        clips = [clip(1, 2000, 2040), clip(2, 500, 540), clip(3, 1000, 1040)]
        chapters = build_chapters(clips, 3600)
        times = [t for t, _ in chapters]
        assert times == sorted(times)

    def test_min_10s_gap_folds_into_previous(self):
        clips = [clip(1, 500, 540), clip(2, 505, 545, title="Zu nah")]
        chapters = build_chapters(clips, 3600)
        titles = [t for _, t in chapters]
        assert "Zu nah" not in titles

    def test_clip_near_zero_second_folds(self):
        # Opener bei 0 (frueher Clip), naechster bei 8s -> gefaltet
        clips = [clip(1, 2, 30, title="Opener"), clip(2, 8, 40, title="Nah")]
        chapters = build_chapters(clips, 3600)
        assert [t for _, t in chapters] == ["Opener"]

    def test_no_clips_single_start(self):
        chapters = build_chapters([], 3600)
        assert chapters == [(0.0, "Start")]

    def test_mm_ss_format_under_hour(self):
        text = render_chapters(build_chapters([clip(1, 725, 760)], 3000))
        assert "12:05" in text

    def test_h_mm_ss_format_over_hour(self):
        text = render_chapters(build_chapters([clip(1, 3725, 3760)], 7200))
        assert "1:02:05" in text

    def test_chapter_beyond_duration_dropped(self):
        chapters = build_chapters([clip(1, 5000, 5040)], 3600)
        assert all(t < 3600 for t, _ in chapters)

    def test_youtube_shape(self):
        # jede Zeile: "<timecode> <titel>"
        text = render_chapters(
            build_chapters([clip(1, 500, 540, title="Mein Titel")], 3600)
        )
        for line in text.strip().splitlines():
            tc = line.split(" ", 1)[0]
            assert all(part.isdigit() for part in tc.split(":"))
