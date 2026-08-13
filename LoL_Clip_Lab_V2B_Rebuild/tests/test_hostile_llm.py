"""Feindliche LLM-Antworten (eigene Testklasse laut Definition of Done):

Infinity, null-Listen, Nicht-Strings, Klammer-Fluten, tiefes Nesting,
Kommas/Pfad-Zeichen in freiem Text.
"""

from __future__ import annotations

import csv
import json

import pytest

from cliplab.config import Config
from cliplab.editorial import parse_moments_response, sanitize_insights, sanitize_moment
from cliplab.output import render_clips_csv
from cliplab.planning import Clip


class TestHostileMoments:
    def test_infinity_score_clamped(self, cfg):
        raw = '{"moments":[{"t0":1,"t1":5,"score":Infinity,"title":"x"}]}'
        m = parse_moments_response(raw, 100, set(), cfg)[0]
        assert 0 <= m.score <= 10

    def test_negative_infinity_punchline(self, cfg):
        raw = '{"moments":[{"t0":1,"t1":5,"punchline_t":-Infinity}]}'
        m = parse_moments_response(raw, 100, set(), cfg)[0]
        assert m.punchline_t == -1.0

    def test_nan_times_rejected(self, cfg):
        raw = '{"moments":[{"t0":NaN,"t1":5}]}'
        assert parse_moments_response(raw, 100, set(), cfg) == []

    def test_null_lists_tolerated(self, cfg):
        m = sanitize_moment(
            {
                "t0": 1,
                "t1": 5,
                "channels": None,
                "captions": None,
                "zooms": None,
                "sfx": None,
                "callback_refs": None,
                "lore_refs": None,
            },
            100,
            set(),
            cfg,
        )
        assert m.channels == [] and m.captions == [] and m.lore_refs == []

    def test_non_string_title(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "title": {"evil": True}}, 100, set(), cfg)
        assert isinstance(m.title, str) and m.title

    def test_numeric_title_stringified(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "title": 12345}, 100, set(), cfg)
        assert m.title == "12345"

    def test_list_as_reason(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "reason": ["a", "b"]}, 100, set(), cfg)
        assert m.reason == ""

    def test_category_path_chars_neutralized(self, cfg):
        m = sanitize_moment(
            {"t0": 1, "t1": 5, "category": "../..\\windows/system32"}, 100, set(), cfg
        )
        assert "/" not in m.category and "\\" not in m.category and ".." not in m.category

    def test_newlines_in_title_collapsed(self, cfg):
        m = sanitize_moment(
            {"t0": 1, "t1": 5, "title": "Zeile1\nZeile2\r\nZeile3"}, 100, set(), cfg
        )
        assert "\n" not in m.title and "\r" not in m.title

    def test_huge_title_capped(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "title": "T" * 10000}, 100, set(), cfg)
        assert len(m.title) <= 90

    def test_moments_as_dict_not_list(self, cfg):
        raw = '{"moments": {"nicht": "liste"}}'
        assert parse_moments_response(raw, 100, set(), cfg) == []

    def test_moment_entries_not_dicts(self, cfg):
        raw = '{"moments": ["string", 42, null, [1,2]]}'
        assert parse_moments_response(raw, 100, set(), cfg) == []

    def test_deep_nesting_no_crash(self, cfg):
        deep = {"t0": 1, "t1": 5}
        cursor = deep
        for _ in range(200):
            cursor["nest"] = {"x": 1}
            cursor = cursor["nest"]
        raw = json.dumps({"moments": [deep]})
        out = parse_moments_response(raw, 100, set(), cfg)
        assert len(out) == 1  # unbekannte Felder ignoriert

    def test_bracket_flood_in_response(self, cfg):
        raw = "{" * 50_000 + '\n{"moments":[]}'
        assert parse_moments_response(raw, 100, set(), cfg) == []

    def test_score_as_string_word(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "score": "zehn!!"}, 100, set(), cfg)
        assert m.score == 5.0  # Default

    def test_bool_score(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "score": True}, 100, set(), cfg)
        assert m.score == 5.0

    def test_channels_with_nested_garbage(self, cfg):
        m = sanitize_moment(
            {"t0": 1, "t1": 5, "channels": [{"name": "insta"}, ["yt"], None, "insta"]},
            100,
            set(),
            cfg,
        )
        assert m.channels == ["insta"]

    def test_captions_flood_capped(self, cfg):
        caps = [{"t": i, "text": f"c{i}"} for i in range(1000)]
        m = sanitize_moment({"t0": 1, "t1": 5, "captions": caps}, 2000, set(), cfg)
        assert len(m.captions) <= 12


class TestHostileInsights:
    def test_gags_as_strings_converted(self):
        ins = sanitize_insights({"running_gags": ["nur ein string"]}, 100)
        assert ins.running_gags[0]["name"] == "nur ein string"

    def test_gags_garbage_skipped(self):
        ins = sanitize_insights({"running_gags": [42, None, [], {"note": "ohne name"}]}, 100)
        assert ins.running_gags == []

    def test_callbacks_payoff_before_setup_dropped(self):
        ins = sanitize_insights(
            {"callbacks": [{"setup_t": 90, "payoff_t": 10}]}, 100
        )
        assert ins.callbacks == []

    def test_callbacks_infinity_dropped(self):
        ins = sanitize_insights(
            {"callbacks": [{"setup_t": 1, "payoff_t": float("inf")}]}, 100
        )
        assert ins.callbacks == []

    def test_non_dict_input(self):
        assert sanitize_insights("garbage", 100).running_gags == []
        assert sanitize_insights(None, 100).running_gags == []
        assert sanitize_insights([1, 2], 100).running_gags == []

    def test_notes_non_strings_filtered(self):
        ins = sanitize_insights({"notes": [1, "ok", None]}, 100)
        assert "ok" in ins.notes

    def test_summary_newlines_collapsed(self):
        ins = sanitize_insights({"summary": "a\nb\nc"}, 100)
        assert "\n" not in ins.summary


class TestFreeTextToOutputs:
    """Kommas/Quotes/Pfad-Zeichen im freien LLM-Text duerfen CSV nicht brechen."""

    def _clip(self, title):
        return Clip(
            rank=1, t0=10, t1=40, title=title, category="funny", final=0.8,
            score=8, signal=1, style="a,b", channels=["insta", "yt"],
            punchline_t=35, punchline_state="ends_just_after", reason="r",
        )

    @pytest.mark.parametrize(
        "title",
        [
            'Titel mit "Quotes" und, Kommas',
            "Pfad C:\\evil\\..\\..\\x",
            "Semikolon; und | Pipe",
            "Umbruch bleibt draussen",
            "🌿 Emoji, alles gut",
        ],
    )
    def test_csv_roundtrip(self, title):
        text = render_clips_csv([self._clip(title)])
        rows = list(csv.reader(text.splitlines()))
        assert len(rows) == 2
        assert rows[1][1] == title  # Titel kommt exakt und gequotet zurueck
        assert rows[1][9] == "insta|yt"  # Kanaele kommasicher

    def test_csv_all_rows_same_width(self):
        text = render_clips_csv([self._clip("a"), self._clip("b,c")])
        rows = list(csv.reader(text.splitlines()))
        assert len({len(r) for r in rows}) == 1
