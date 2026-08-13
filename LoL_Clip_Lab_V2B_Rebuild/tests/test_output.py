"""F12: Ausgaben — Sheet, JSON, CSV, Kapitel."""

from __future__ import annotations

import csv
import json

import pytest

from cliplab.channels import build_channel_plans, build_chapters
from cliplab.config import Config
from cliplab.output import (
    build_plan_dict,
    excerpt_for_clip,
    punchline_line,
    render_clips_csv,
    render_edit_sheet,
    write_outputs,
)
from cliplab.planning import Clip
from tests.conftest import make_segment


def sample_clip(**kw):
    defaults = dict(
        rank=1, t0=100.0, t1=140.0, title="Mein Clip", category="funny",
        final=0.87, score=8.5, signal=1.0, style="insta_funny",
        channels=["insta", "yt"], punchline_t=135.0,
        punchline_state="ends_just_after", reason="Weil lustig.",
        captions=[{"t": 105.0, "text": "CAP"}],
        zooms=[{"t": 135.0, "duration": 1.5}],
        sfx=[{"t": 136.0, "kind": "boom"}],
        callback_refs=[{"t": 20.0, "note": "Setup"}],
        lore_refs=["Der Busch"],
    )
    defaults.update(kw)
    return Clip(**defaults)


def segments():
    return [
        make_segment(95, 105, "Anfang vom Clip mit Setup und allem drum und dran"),
        make_segment(110, 120, "Mittelteil " + "bla " * 100),
        make_segment(130, 139, "Und hier kommt die grosse Pointe am Ende"),
    ]


class TestExcerpt:
    def test_head_and_tail_survive(self):
        text = excerpt_for_clip(segments(), 100, 140, head_chars=60, tail_chars=40)
        assert "Anfang" in text
        assert "Pointe am Ende" in text  # das Ende faellt NICHT dem Truncating zum Opfer
        assert "[…]" in text

    def test_short_text_untruncated(self):
        text = excerpt_for_clip([make_segment(100, 110, "kurz")], 100, 140)
        assert text == "kurz"

    def test_no_segments_empty(self):
        assert excerpt_for_clip([], 100, 140) == ""

    def test_only_overlapping_segments(self):
        segs = [make_segment(0, 50, "vorher"), make_segment(100, 110, "drin")]
        text = excerpt_for_clip(segs, 100, 140)
        assert "vorher" not in text and "drin" in text


class TestPunchlineLine:
    def test_ends_just_after(self):
        line = punchline_line(sample_clip())
        assert "endet kurz nach der Pointe" in line

    def test_runs_on_honest(self):
        line = punchline_line(sample_clip(punchline_state="runs_on"))
        assert "laeuft nach der Pointe weiter" in line and "⚠️" in line

    def test_unknown(self):
        line = punchline_line(sample_clip(punchline_t=-1, punchline_state="unknown"))
        assert "unbekannt" in line

    def test_cut_off(self):
        line = punchline_line(sample_clip(punchline_state="punchline_cut"))
        assert "HINTER" in line


class TestSheet:
    def _sheet(self, cfg, clips=None, memory_state=None, warnings=None, mode="LLM-Editorial"):
        clips = clips if clips is not None else [sample_clip()]
        plans = build_channel_plans(clips, cfg, None)
        return render_edit_sheet(
            "vod.mkv", 3600, mode,
            {"segments": 3, "reactions": 2, "events": 1, "candidates": 2, "moments": 1},
            clips, plans, segments(), memory_state, "2026-01-01", warnings=warnings,
        )

    def test_header_stats(self, cfg):
        sheet = self._sheet(cfg)
        assert "vod.mkv" in sheet and "1:00:00" in sheet
        assert "3 Transkript-Segmente" in sheet and "2 Reaktionen" in sheet

    def test_clip_section_complete(self, cfg):
        sheet = self._sheet(cfg)
        assert "#1 😂 Mein Clip" in sheet
        assert "Cut as: insta_funny" in sheet
        assert "Channels: insta, yt" in sheet
        assert "01:40 → 02:20" in sheet
        assert "Warum: Weil lustig." in sheet
        assert "Captions:" in sheet and "CAP" in sheet
        assert "Zooms:" in sheet
        assert "SFX:" in sheet and "boom" in sheet
        assert "Callback-Insert" in sheet
        assert "🧠 Lore" in sheet and "Der Busch" in sheet

    def test_memory_state_shown(self, cfg):
        state = {
            "gags_known": 3,
            "sessions_known": 2,
            "gags_by_slug": {"der_busch": {"name": "Der Busch", "times_seen": 2}},
        }
        sheet = self._sheet(cfg, memory_state=state)
        assert "3 Running Gags bekannt" in sheet
        assert "(2x gesehen)" in sheet

    def test_memory_off_marked(self, cfg):
        sheet = self._sheet(cfg, memory_state=None)
        assert "Gedaechtnis: aus" in sheet

    def test_signal_only_marked(self, cfg):
        sheet = self._sheet(cfg, mode="Signal-only — keine LLM-CLI verfuegbar")
        assert "Signal-only" in sheet

    def test_warnings_section(self, cfg):
        sheet = self._sheet(cfg, warnings=["Etwas fehlte"])
        assert "Hinweise" in sheet and "Etwas fehlte" in sheet

    def test_no_clips_message(self, cfg):
        sheet = self._sheet(cfg, clips=[])
        assert "keine Clips" in sheet

    def test_second_opinion_line(self, cfg):
        sheet = self._sheet(cfg, clips=[sample_clip(second_score=6.0)])
        assert "Zweitmeinung: 6.0/10" in sheet

    def test_llm2_source_line(self, cfg):
        sheet = self._sheet(cfg, clips=[sample_clip(source="llm2", second_score=None)])
        assert "Zweitmeinung" in sheet

    def test_channel_plans_at_end(self, cfg):
        sheet = self._sheet(cfg)
        assert sheet.index("Kanal-Plaene") > sheet.index("Mein Clip")
        assert "chapters.txt" in sheet


class TestCsvAndPlan:
    def test_csv_parsebar_with_commas(self):
        clips = [sample_clip(title='Titel, mit "Quotes"')]
        rows = list(csv.reader(render_clips_csv(clips).splitlines()))
        assert rows[1][1] == 'Titel, mit "Quotes"'

    def test_csv_channels_pipe_joined(self):
        rows = list(csv.reader(render_clips_csv([sample_clip()]).splitlines()))
        assert rows[1][rows[0].index("channels")] == "insta|yt"

    def test_csv_header_present(self):
        rows = list(csv.reader(render_clips_csv([]).splitlines()))
        assert rows[0][0] == "rank" and "punchline_t" in rows[0]

    def test_plan_dict_complete(self, cfg):
        clips = [sample_clip()]
        plans = build_channel_plans(clips, cfg, None)
        chapters = build_chapters(clips, 3600)
        plan = build_plan_dict("vod.mkv", 3600, "llm", {}, clips, plans, chapters, "2026-01-01")
        assert plan["version"] == 1
        assert plan["clips"][0]["title"] == "Mein Clip"
        assert plan["channels"][0]["name"] == "insta"
        assert plan["chapters"][0]["t"] == 0.0

    def test_write_outputs_four_files(self, tmp_path, cfg):
        clips = [sample_clip()]
        plans = build_channel_plans(clips, cfg, None)
        chapters = build_chapters(clips, 3600)
        plan = build_plan_dict("v", 3600, "llm", {}, clips, plans, chapters, "2026-01-01")
        paths = write_outputs(tmp_path / "out", "SHEET", plan, clips, chapters)
        assert paths["sheet"].read_text(encoding="utf-8") == "SHEET"
        assert json.loads(paths["plan"].read_text(encoding="utf-8"))["vod"] == "v"
        assert paths["csv"].is_file()
        assert paths["chapters"].read_text(encoding="utf-8").startswith("00:00")
