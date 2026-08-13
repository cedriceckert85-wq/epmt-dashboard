"""F5: Kandidaten, Match-Geometrie, Session-Pass, Moment-Pass."""

from __future__ import annotations

import json

import pytest

from cliplab.config import Config
from cliplab.editorial import (
    MOMENT_MARKER,
    SESSION_MARKER,
    Candidate,
    Moment,
    attach_candidates,
    build_candidates,
    build_moment_context,
    build_moment_prompt,
    dedupe_moments,
    moment_pass,
    moments_from_candidates,
    parse_moments_response,
    sanitize_moment,
    session_pass,
    windows_match,
)
from cliplab.events import GameEvent
from cliplab.reactions import Reaction
from cliplab.timeline import build_entries
from tests.conftest import FakeRunner, make_moment, make_segment


class TestCandidates:
    def test_single_event_is_point(self):
        cands = build_candidates([], [GameEvent(t=100, kind="penta", weight=5.0)])
        assert len(cands) == 1 and cands[0].is_point
        assert cands[0].t0 == cands[0].t1 == 100

    def test_negative_event_no_candidate(self):
        cands = build_candidates([], [GameEvent(t=100, kind="death", weight=-1.5)])
        assert cands == []

    def test_reaction_has_extent(self):
        cands = build_candidates([Reaction(t=50, t0=48, t1=53, intensity=0.9)], [])
        assert not cands[0].is_point

    def test_nearby_merged(self):
        cands = build_candidates(
            [Reaction(t=100, t0=99, t1=101, intensity=0.5)],
            [GameEvent(t=103, kind="penta", weight=5.0)],
        )
        assert len(cands) == 1
        c = cands[0]
        assert c.t0 == 99 and c.t1 == 103
        assert c.signal > 0.5  # kombiniert

    def test_far_apart_not_merged(self):
        cands = build_candidates(
            [Reaction(t=100, t0=99, t1=101, intensity=0.5)],
            [GameEvent(t=200, kind="penta", weight=5.0)],
        )
        assert len(cands) == 2

    def test_sorted_by_time(self):
        cands = build_candidates(
            [Reaction(t=300, t0=299, t1=301, intensity=0.5)],
            [GameEvent(t=100, kind="kill", weight=1.0)],
        )
        assert cands[0].peak_t < cands[1].peak_t

    def test_empty(self):
        assert build_candidates([], []) == []


class TestGeometry:
    def test_point_in_window_matches(self):
        assert windows_match(10, 20, 15, 15)

    def test_point_on_edge_matches(self):
        assert windows_match(10, 20, 20, 20)
        assert windows_match(10, 20, 10, 10)

    def test_point_outside_no_match(self):
        assert not windows_match(10, 20, 25, 25)

    def test_real_overlap_matches(self):
        assert windows_match(10, 20, 15, 30)

    def test_edge_touch_two_windows_no_match(self):
        assert not windows_match(10, 20, 20, 30)

    def test_containment_matches(self):
        assert windows_match(10, 40, 20, 30)

    def test_identical_points_match(self):
        assert windows_match(15, 15, 15, 15)

    def test_different_points_no_match(self):
        assert not windows_match(15, 15, 16, 16)

    def test_moment_point_in_candidate_window(self):
        assert windows_match(15, 15, 10, 20)


class TestDedupe:
    def test_identical_windows_are_duplicates(self):
        a = make_moment(10, 20, score=5)
        b = make_moment(10, 20, score=8)
        kept = dedupe_moments([a, b])
        assert len(kept) == 1 and kept[0].score == 8

    def test_identical_point_windows_are_duplicates(self):
        a = make_moment(15, 15, score=5)
        b = make_moment(15, 15, score=3)
        assert len(dedupe_moments([a, b])) == 1

    def test_different_windows_kept(self):
        assert len(dedupe_moments([make_moment(10, 20), make_moment(30, 40)])) == 2

    def test_near_identical_within_epsilon(self):
        assert len(dedupe_moments([make_moment(10, 20), make_moment(10.005, 20.005)])) == 1


class TestAttach:
    def test_matched_takes_signal_and_consumes(self):
        m = make_moment(90, 130)
        cands = [Candidate(t0=100, t1=100, peak_t=100, signal=1.2)]
        consumed = attach_candidates([m], cands)
        assert consumed == {0}
        assert m.signal == 1.2

    def test_moment_keeps_llm_window(self):
        m = make_moment(90, 130)
        attach_candidates([m], [Candidate(t0=100, t1=105, peak_t=100, signal=0.5)])
        assert (m.t0, m.t1) == (90, 130)  # LLM-Fenster uebernommen

    def test_unmatched_candidate_not_consumed(self):
        m = make_moment(90, 95)
        consumed = attach_candidates([m], [Candidate(t0=500, t1=500, peak_t=500, signal=1.0)])
        assert consumed == set()

    def test_strongest_signal_wins(self):
        m = make_moment(90, 130)
        cands = [
            Candidate(t0=100, t1=100, peak_t=100, signal=0.4),
            Candidate(t0=120, t1=120, peak_t=120, signal=1.1),
        ]
        attach_candidates([m], cands)
        assert m.signal == 1.1


class TestSignalOnly:
    def test_candidates_become_moments(self):
        cands = build_candidates(
            [Reaction(t=50, t0=48, t1=53, intensity=0.8)],
            [GameEvent(t=200, kind="penta", weight=5.0)],
        )
        moments = moments_from_candidates(cands)
        assert len(moments) == 2
        assert all(m.source == "signal" for m in moments)
        assert all(m.score == 0.0 for m in moments)
        assert all(not m.from_llm_window for m in moments)

    def test_event_title_mentions_kind(self):
        moments = moments_from_candidates(
            build_candidates([], [GameEvent(t=200, kind="penta", weight=5.0)])
        )
        assert "penta" in moments[0].title


class TestSessionPass:
    def test_none_runner_empty(self, cfg):
        ins = session_pass(cfg, "doc", 100, None)
        assert ins.running_gags == []

    def test_single_chunk_parsed(self, cfg):
        resp = json.dumps(
            {
                "running_gags": [{"name": "Busch", "first_t": 10, "note": "n"}],
                "callbacks": [{"setup_t": 10, "payoff_t": 90, "note": "cb"}],
                "arcs": [{"t0": 0, "t1": 50, "title": "arc"}],
                "catchphrases": ["c1"],
                "lore": ["l1"],
                "notes": ["n1"],
                "summary": "s",
            }
        )
        runner = FakeRunner(responses=[resp])
        ins = session_pass(cfg, "kurzes doc", 100, runner)
        assert ins.running_gags[0]["name"] == "Busch"
        assert ins.callbacks[0]["payoff_t"] == 90
        assert ins.summary == "s"
        assert SESSION_MARKER in runner.prompts[0]

    def test_chunked_carries_previous_findings(self, cfg):
        cfg.chunk_chars = 5000
        doc = "\n".join(f"[t={i}] TALK: zeile {i} " + "x" * 80 for i in range(200))
        r1 = json.dumps({"running_gags": [{"name": "GagFrueh", "first_t": 5}], "summary": "a"})
        r2 = json.dumps({"running_gags": [{"name": "GagSpaet", "first_t": 150}], "summary": "b"})
        runner = FakeRunner(responses=[r1, r2, r2, r2, r2, r2])
        ins = session_pass(cfg, doc, 200, runner)
        assert len(runner.prompts) >= 2
        # Funde des ersten Chunks werden in den zweiten Prompt mitgegeben
        assert "GagFrueh" in runner.prompts[1]
        names = [g["name"] for g in ins.running_gags]
        assert "GagFrueh" in names and "GagSpaet" in names

    def test_gags_deduped_across_chunks(self, cfg):
        cfg.chunk_chars = 5000
        doc = "\n".join("zeile " + "x" * 90 for _ in range(200))
        r = json.dumps({"running_gags": [{"name": "Der Busch"}]})
        runner = FakeRunner(by_marker={SESSION_MARKER: r})
        ins = session_pass(cfg, doc, 200, runner)
        assert len([g for g in ins.running_gags if g["name"] == "Der Busch"]) == 1

    def test_garbage_response_ignored(self, cfg):
        runner = FakeRunner(responses=["voellig kaputt, kein json"])
        ins = session_pass(cfg, "doc", 100, runner)
        assert ins.running_gags == []

    def test_memory_block_in_prompt(self, cfg):
        runner = FakeRunner(responses=["{}"])
        session_pass(cfg, "doc", 100, runner, memory_block="Bekannter Gag: XYZ")
        assert "Bekannter Gag: XYZ" in runner.prompts[0]

    def test_setup_payoff_hours_apart_survive(self, cfg):
        # Gag aus Minute 3 mit Payoff in Stunde 3 MUSS verbindbar sein
        cfg.chunk_chars = 5000
        doc = "\n".join(f"[t={i * 60}] TALK: " + "x" * 90 for i in range(200))
        r_early = json.dumps({"callbacks": []})
        r_late = json.dumps(
            {"callbacks": [{"setup_t": 180, "payoff_t": 10800, "note": "spaet"}]}
        )
        responses = [r_early] * 2 + [r_late] * 10
        runner = FakeRunner(responses=responses)
        ins = session_pass(cfg, doc, 11000, runner)
        assert any(c["setup_t"] == 180 and c["payoff_t"] == 10800 for c in ins.callbacks)


class TestMomentContext:
    def _entries(self, n=200, step=10):
        return build_entries(
            [make_segment(i * step, i * step + 5, f"segment nummer {i}") for i in range(n)],
            [],
            [],
        )

    def test_every_candidate_has_context(self, cfg):
        entries = self._entries()
        cands = [
            Candidate(t0=t, t1=t, peak_t=t, signal=1.0) for t in (50, 500, 1500, 1950)
        ]
        ctx = build_moment_context(entries, cands, budget_chars=8000, window_s=90)
        for i in range(1, 5):
            assert f"KANDIDAT {i}:" in ctx

    def test_late_sparse_candidate_keeps_context_tight_budget(self, cfg):
        entries = self._entries()
        cands = [Candidate(t0=t, t1=t, peak_t=t, signal=1.0) for t in range(0, 1900, 100)]
        ctx = build_moment_context(entries, cands, budget_chars=3000, window_s=90)
        # auch der letzte Kandidat behaelt mindestens eine Kontextzeile
        assert f"KANDIDAT {len(cands)}:" in ctx
        last_block = ctx.split(f"KANDIDAT {len(cands)}:")[1]
        assert "segment nummer" in last_block

    def test_rest_sampled_uniformly(self, cfg):
        entries = self._entries()
        cands = [Candidate(t0=500, t1=500, peak_t=500, signal=1.0)]
        ctx = build_moment_context(entries, cands, budget_chars=20000, window_s=90)
        assert "STICHPROBE" in ctx
        # Zeilen weit weg vom Kandidaten tauchen in der Stichprobe auf
        assert "segment nummer 190" in ctx or "segment nummer 180" in ctx

    def test_candidate_without_nearby_lines_gets_nearest(self, cfg):
        entries = build_entries([make_segment(0, 5, "nur ganz frueh")], [], [])
        cands = [Candidate(t0=5000, t1=5000, peak_t=5000, signal=1.0)]
        ctx = build_moment_context(entries, cands, budget_chars=5000, window_s=90)
        assert "nur ganz frueh" in ctx

    def test_empty_entries(self, cfg):
        assert "keine Timeline" in build_moment_context([], [], 5000, 90)


class TestMomentPrompt:
    def test_styles_all_names_reach_prompt(self, cfg):
        cut_styles = {
            f"stil_{i}": {"ideal_len_s": 30, "cuts_per_min": 5, "notes": "N" * 500}
            for i in range(20)
        }
        prompt = build_moment_prompt(cfg, [], [], _empty_insights(), cut_styles, "", 100)
        for name in cut_styles:
            assert name in prompt

    def test_channels_with_notes_in_prompt(self, cfg):
        prompt = build_moment_prompt(cfg, [], [], _empty_insights(), {}, "", 100)
        assert "insta" in prompt and "yt" in prompt and "uncut" in prompt
        assert "Ganz-VOD" in prompt

    def test_hosts_in_prompt(self, cfg):
        cfg.hosts = ["Jonas", "Basti"]
        prompt = build_moment_prompt(cfg, [], [], _empty_insights(), {}, "", 100)
        assert "Jonas" in prompt and "Basti" in prompt

    def test_language_auto_rule(self, cfg):
        prompt = build_moment_prompt(cfg, [], [], _empty_insights(), {}, "", 100)
        assert "SPRACHE" in prompt

    def test_language_forced(self, cfg):
        cfg.language = "de"
        prompt = build_moment_prompt(cfg, [], [], _empty_insights(), {}, "", 100)
        assert "'de'" in prompt

    def test_own_discoveries_allowed(self, cfg):
        prompt = build_moment_prompt(cfg, [], [], _empty_insights(), {}, "", 100)
        assert "eigene Momente" in prompt

    def test_moment_pass_returns_prompt_for_dualbrain(self, cfg):
        runner = FakeRunner(responses=['{"moments": []}'])
        moments, prompt = moment_pass(cfg, [], [], _empty_insights(), {}, "", 100, runner)
        assert MOMENT_MARKER in prompt
        assert runner.prompts[0] == prompt


def _empty_insights():
    from cliplab.editorial import SessionInsights

    return SessionInsights()


class TestSanitizeMoment:
    def test_valid_moment(self, cfg):
        raw = {
            "t0": 10,
            "t1": 50,
            "title": "Titel",
            "category": "funny",
            "score": 8.5,
            "punchline_t": 45,
            "reason": "weil",
            "style": "insta_funny",
            "channels": ["insta", "yt"],
            "captions": [{"t": 12, "text": "cap"}],
            "zooms": [{"t": 45, "duration": 2}],
            "sfx": [{"t": 46, "kind": "boom"}],
            "callback_refs": [{"t": 5, "note": "setup"}],
            "lore_refs": ["Gag"],
        }
        m = sanitize_moment(raw, 100, {"insta_funny"}, cfg)
        assert m is not None
        assert m.style == "insta_funny"
        assert m.channels == ["insta", "yt"]
        assert m.from_llm_window

    def test_reversed_window_swapped(self, cfg):
        m = sanitize_moment({"t0": 50, "t1": 10, "title": "x"}, 100, set(), cfg)
        assert (m.t0, m.t1) == (10, 50)

    def test_missing_times_rejected(self, cfg):
        assert sanitize_moment({"title": "x"}, 100, set(), cfg) is None

    def test_unknown_style_dropped(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "style": "fantasie"}, 100, {"insta_funny"}, cfg)
        assert m.style == ""

    def test_unknown_channels_dropped(self, cfg):
        m = sanitize_moment({"t0": 1, "t1": 5, "channels": ["tiktok", "yt"]}, 100, set(), cfg)
        assert m.channels == ["yt"]

    def test_style_implies_channel(self, cfg):
        # Kohaerenz-Regel: insta_funny -> Kanal insta automatisch
        m = sanitize_moment(
            {"t0": 1, "t1": 5, "style": "insta_funny", "channels": ["yt"]},
            100,
            {"insta_funny"},
            cfg,
        )
        assert "insta" in m.channels and "yt" in m.channels

    def test_style_never_implies_full_channel(self, cfg):
        m = sanitize_moment(
            {"t0": 1, "t1": 5, "style": "uncut_x", "channels": []},
            100,
            {"uncut_x"},
            cfg,
        )
        assert "uncut" not in m.channels

    def test_callback_refs_floats_accepted(self, cfg):
        m = sanitize_moment({"t0": 10, "t1": 20, "callback_refs": [5.0, 7.5]}, 100, set(), cfg)
        assert [r["t"] for r in m.callback_refs] == [5.0, 7.5]

    def test_title_fallback(self, cfg):
        m = sanitize_moment({"t0": 65, "t1": 80}, 100, set(), cfg)
        assert m.title  # nie leer

    def test_times_clamped_to_duration(self, cfg):
        m = sanitize_moment({"t0": 50, "t1": 9999}, 100, set(), cfg)
        assert m.t1 == 100

    def test_point_window_not_llm_window(self, cfg):
        m = sanitize_moment({"t0": 50, "t1": 50.5, "title": "kurz"}, 100, set(), cfg)
        assert m is not None and not m.from_llm_window


class TestParseResponse:
    def test_object_with_moments(self, cfg):
        raw = json.dumps({"moments": [{"t0": 1, "t1": 5, "title": "a"}]})
        assert len(parse_moments_response(raw, 100, set(), cfg)) == 1

    def test_bare_array(self, cfg):
        raw = json.dumps([{"t0": 1, "t1": 5, "title": "a"}])
        assert len(parse_moments_response(raw, 100, set(), cfg)) == 1

    def test_chatty_response(self, cfg):
        raw = 'Hier!\n```json\n{"moments": [{"t0": 1, "t1": 5}]}\n```'
        assert len(parse_moments_response(raw, 100, set(), cfg)) == 1

    def test_none(self, cfg):
        assert parse_moments_response(None, 100, set(), cfg) == []

    def test_garbage(self, cfg):
        assert parse_moments_response("kein json", 100, set(), cfg) == []

    def test_max_moments_capped(self, cfg):
        raw = json.dumps({"moments": [{"t0": i, "t1": i + 1} for i in range(0, 99)]})
        out = parse_moments_response(raw, 200, set(), cfg, max_moments=10)
        assert len(out) == 10
