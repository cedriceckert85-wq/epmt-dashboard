"""F9: Doppel-Gehirn — identischer Prompt, Blend-Semantik, Default AUS."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cliplab.config import Config
from cliplab.dualbrain import blend_second_opinion
from tests.conftest import FakeRunner, make_moment


def secondary_response(moments):
    return json.dumps({"moments": moments})


class TestDefaultOff:
    def test_code_default_empty(self):
        assert Config().llm2_cmd == []

    def test_config_template_ships_disabled(self):
        template = (Path(__file__).resolve().parent.parent / "config.toml").read_text(
            encoding="utf-8"
        )
        # aktive llm2_cmd-Zeile muss leere Liste sein
        active = [
            line for line in template.splitlines()
            if line.strip().startswith("llm2_cmd") and not line.strip().startswith("#")
        ]
        assert active == ["llm2_cmd = []"]

    def test_no_runner_returns_primary_unchanged(self, cfg):
        primary = [make_moment(10, 20, score=8)]
        out, notes = blend_second_opinion(primary, "prompt", None, 100, set(), cfg)
        assert out is primary and notes == []


class TestBlend:
    def test_identical_prompt_passed(self, cfg):
        runner = FakeRunner(responses=[secondary_response([])])
        blend_second_opinion([], "DER MOMENT-PROMPT", runner, 100, set(), cfg)
        assert runner.prompts == ["DER MOMENT-PROMPT"]

    def test_both_scored_mean_plus_note(self, cfg):
        primary = [make_moment(10, 40, score=8.0, title="Primaertitel")]
        runner = FakeRunner(
            responses=[secondary_response([{"t0": 15, "t1": 35, "score": 4.0, "title": "Anders"}])]
        )
        out, notes = blend_second_opinion(primary, "p", runner, 100, set(), cfg)
        assert len(out) == 1
        assert out[0].score == 6.0  # Mittelwert
        assert out[0].second_score == 4.0  # Notiz
        assert any("doppelt bewertet" in n for n in notes)

    def test_primary_work_never_overwritten_even_score_zero(self, cfg):
        primary = [
            make_moment(
                10, 40, score=8.0, title="MEIN TITEL",
                captions=[{"t": 12, "text": "MEINE CAPTION"}],
            )
        ]
        runner = FakeRunner(
            responses=[
                secondary_response(
                    [{
                        "t0": 10, "t1": 40, "score": 0.0, "title": "BOESER TITEL",
                        "captions": [{"t": 13, "text": "ANDERE"}],
                    }]
                )
            ]
        )
        out, _ = blend_second_opinion(primary, "p", runner, 100, set(), cfg)
        assert out[0].title == "MEIN TITEL"
        assert out[0].captions == [{"t": 12, "text": "MEINE CAPTION"}]
        assert out[0].score == 4.0  # (8+0)/2 — aber Inhalte unangetastet

    def test_skipped_by_primary_adopted(self, cfg):
        primary = [make_moment(10, 40, score=8)]
        runner = FakeRunner(
            responses=[secondary_response([{"t0": 200, "t1": 240, "score": 7, "title": "Neu"}])]
        )
        out, notes = blend_second_opinion(primary, "p", runner, 100_000, set(), cfg)
        assert len(out) == 2
        adopted = out[1]
        assert adopted.source == "llm2"
        assert "Zweitmeinung" in adopted.reason
        assert any("uebernommen" in n for n in notes)

    def test_new_windows_not_matched_against_own_findings(self, cfg):
        # zwei ueberlappende NEUE Fenster der Zweitmeinung: beide bleiben
        # eigenstaendig (kein Score-Blending untereinander)
        runner = FakeRunner(
            responses=[
                secondary_response(
                    [
                        {"t0": 200, "t1": 240, "score": 7, "title": "A"},
                        {"t0": 220, "t1": 260, "score": 3, "title": "B"},
                    ]
                )
            ]
        )
        out, _ = blend_second_opinion([], "p", runner, 100_000, set(), cfg)
        scores = sorted(m.score for m in out)
        assert scores == [3.0, 7.0]  # keine Mittelung untereinander

    def test_duplicate_new_windows_not_created(self, cfg):
        runner = FakeRunner(
            responses=[
                secondary_response(
                    [
                        {"t0": 200, "t1": 240, "score": 7, "title": "A"},
                        {"t0": 200, "t1": 240, "score": 9, "title": "A nochmal"},
                    ]
                )
            ]
        )
        out, _ = blend_second_opinion([], "p", runner, 100_000, set(), cfg)
        assert len(out) == 1

    def test_garbage_response_leaves_primary_untouched(self, cfg):
        primary = [make_moment(10, 40, score=8)]
        runner = FakeRunner(responses=["voelliger muell ohne json"])
        out, notes = blend_second_opinion(primary, "p", runner, 100, set(), cfg)
        assert out == primary and out[0].score == 8

    def test_none_response_skipped_silently(self, cfg):
        primary = [make_moment(10, 40, score=8)]
        runner = FakeRunner(responses=[None])
        out, _ = blend_second_opinion(primary, "p", runner, 100, set(), cfg)
        assert out == primary

    def test_runner_exception_never_kills_run(self, cfg):
        def boom(prompt):
            raise RuntimeError("cli explodiert")

        primary = [make_moment(10, 40, score=8)]
        out, notes = blend_second_opinion(primary, "p", boom, 100, set(), cfg)
        assert out == primary and notes

    def test_multiple_secondary_match_same_primary_only_one_blend(self, cfg):
        primary = [make_moment(10, 40, score=8)]
        runner = FakeRunner(
            responses=[
                secondary_response(
                    [
                        {"t0": 12, "t1": 20, "score": 4},
                        {"t0": 25, "t1": 38, "score": 0},
                    ]
                )
            ]
        )
        out, _ = blend_second_opinion(primary, "p", runner, 100, set(), cfg)
        assert len(out) == 1
        assert out[0].score == 6.0  # nur erster Match gemittelt

    def test_point_candidate_geometry_used(self, cfg):
        # Zweitmeinungs-Fenster um ein punktfoermiges Primaer-Moment
        primary = [make_moment(50, 50, score=6)]
        runner = FakeRunner(
            responses=[secondary_response([{"t0": 40, "t1": 60, "score": 8}])]
        )
        out, _ = blend_second_opinion(primary, "p", runner, 100, set(), cfg)
        assert len(out) == 1 and out[0].score == 7.0

    def test_secondary_styles_sanitized(self, cfg):
        runner = FakeRunner(
            responses=[
                secondary_response(
                    [{"t0": 200, "t1": 240, "score": 7, "style": "boeser_stil"}]
                )
            ]
        )
        out, _ = blend_second_opinion([], "p", runner, 100_000, {"insta_funny"}, cfg)
        assert out[0].style == ""
