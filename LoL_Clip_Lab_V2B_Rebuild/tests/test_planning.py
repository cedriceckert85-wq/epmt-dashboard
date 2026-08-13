"""F11: Schnittplanung — Punchline, Setup-Vorlauf, Media-Grenzen, Overlap."""

from __future__ import annotations

import pytest

from cliplab.config import Config
from cliplab.planning import (
    PUNCHLINE_OK,
    PUNCHLINE_RUNS_ON,
    plan_clips,
    plan_window,
)
from cliplab.styles import StyleProfile
from tests.conftest import make_moment


class TestPunchline:
    def test_end_shortly_after_punchline(self, cfg):
        m = make_moment(100, 160, punchline_t=140.0)
        t0, t1, state = plan_window(m, 3600, cfg, None)
        assert t1 == pytest.approx(140.0 + cfg.punchline_decay_s)
        assert state == PUNCHLINE_OK

    def test_extends_to_punchline_if_window_short(self, cfg):
        m = make_moment(100, 120, punchline_t=130.0)
        t0, t1, state = plan_window(m, 3600, cfg, None)
        assert t1 == pytest.approx(130.0 + cfg.punchline_decay_s)

    def test_punchline_before_window_ignored(self, cfg):
        m = make_moment(100, 140, punchline_t=50.0)
        t0, t1, _ = plan_window(m, 3600, cfg, None)
        assert t1 == 140.0

    def test_absurd_late_punchline_ignored(self, cfg):
        m = make_moment(100, 140, punchline_t=500.0)
        t0, t1, _ = plan_window(m, 3600, cfg, None)
        assert t1 == 140.0

    def test_runs_on_state_reported(self, cfg):
        # Pointe ganz am VOD-Anfang: Mindestlaenge + Schieben zwingen das
        # Ende weit hinter die Pointe -> ehrliche "runs_on"-Meldung
        m = make_moment(0.0, 6.0, punchline_t=2.0, from_llm_window=True)
        t0, t1, state = plan_window(m, 3600, cfg, None)
        assert t1 - 2.0 > cfg.punchline_decay_s + 1.0
        assert state == PUNCHLINE_RUNS_ON

    def test_unknown_without_punchline(self, cfg):
        m = make_moment(100, 140, punchline_t=-1.0)
        _, _, state = plan_window(m, 3600, cfg, None)
        assert state == "unknown"


class TestSetupLead:
    def test_llm_window_gets_no_extra_lead(self, cfg):
        m = make_moment(100, 140)  # from_llm_window=True (Default)
        t0, t1, _ = plan_window(m, 3600, cfg, None)
        assert t0 == 100.0  # kein zusaetzlicher Vorlauf

    def test_point_moment_gets_category_lead(self, cfg):
        m = make_moment(500, 500, category="clutch", from_llm_window=False)
        t0, t1, _ = plan_window(m, 3600, cfg, None)
        assert t0 == pytest.approx(500 - 15.0)  # clutch-Vorlauf
        assert t1 > 500

    def test_category_leads_differ(self, cfg):
        clutch = make_moment(500, 500, category="clutch", from_llm_window=False)
        fail = make_moment(500, 500, category="fail", from_llm_window=False)
        t0c, _, _ = plan_window(clutch, 3600, cfg, None)
        t0f, _, _ = plan_window(fail, 3600, cfg, None)
        assert t0c < t0f  # clutch braucht mehr Setup

    def test_unknown_category_default_lead(self, cfg):
        m = make_moment(500, 500, category="selfmade", from_llm_window=False)
        t0, _, _ = plan_window(m, 3600, cfg, None)
        assert t0 == pytest.approx(500 - 8.0)


class TestLengths:
    def test_max_length_trims_start_keeps_end(self, cfg):
        m = make_moment(100, 300, punchline_t=-1)
        t0, t1, _ = plan_window(m, 3600, cfg, None)
        assert t1 == 300.0
        assert t1 - t0 == pytest.approx(cfg.max_clip_s)

    def test_min_length_extends_setup(self, cfg):
        m = make_moment(100, 102)
        t0, t1, _ = plan_window(m, 3600, cfg, None)
        assert t1 - t0 >= cfg.min_clip_s

    def test_style_target_overrides_max_up_to_cap(self, cfg):
        prof = StyleProfile()
        prof.cuts["montage"] = {"ideal_len_s": 80.0}
        m = make_moment(100, 250, style="montage", punchline_t=-1)
        t0, t1, _ = plan_window(m, 3600, cfg, prof)
        assert t1 - t0 == pytest.approx(80.0)

    def test_style_target_capped_at_90(self, cfg):
        prof = StyleProfile()
        prof.cuts["lang"] = {"ideal_len_s": 300.0}
        m = make_moment(100, 500, style="lang", punchline_t=-1)
        t0, t1, _ = plan_window(m, 3600, cfg, prof)
        assert t1 - t0 <= cfg.style_max_cap_s + 0.01

    def test_short_style_does_not_shrink_generic_max(self, cfg):
        prof = StyleProfile()
        prof.cuts["kurz"] = {"ideal_len_s": 20.0}
        m = make_moment(100, 150, style="kurz", punchline_t=-1)
        t0, t1, _ = plan_window(m, 3600, cfg, prof)
        assert t1 - t0 == pytest.approx(50.0)  # LLM-Fenster bleibt


class TestMediaBounds:
    def test_shift_at_start_keeps_min_length(self, cfg):
        # Penta bei Sekunde 2: Fenster wird GESCHOBEN, nicht geklemmt
        m = make_moment(2, 2, category="clutch", from_llm_window=False)
        t0, t1, _ = plan_window(m, 3600, cfg, None)
        assert t0 == 0.0
        assert t1 - t0 >= cfg.min_clip_s

    def test_shift_at_end_keeps_length(self, cfg):
        # Penta in den letzten Sekunden!
        m = make_moment(3598, 3598, category="clutch", from_llm_window=False)
        t0, t1, _ = plan_window(m, 3600.0, cfg, None)
        assert t1 == 3600.0
        assert t1 - t0 >= cfg.min_clip_s

    def test_vod_shorter_than_min_whole_vod(self, cfg):
        m = make_moment(3, 4)
        t0, t1, _ = plan_window(m, 5.0, cfg, None)
        assert (t0, t1) == (0.0, 5.0)

    def test_window_never_outside_media(self, cfg):
        for t in (0, 1, 1800, 3599, 3600):
            m = make_moment(float(t), float(t), from_llm_window=False)
            t0, t1, _ = plan_window(m, 3600.0, cfg, None)
            assert 0 <= t0 < t1 <= 3600.0


class TestPlanClips:
    def _ranked(self, *moments):
        for i, m in enumerate(moments, start=1):
            m.rank = i
            m.final = 1.0 - i * 0.05
        return list(moments)

    def test_overlap_better_wins(self, cfg):
        best = make_moment(100, 150, title="best")
        worse = make_moment(140, 190, title="worse")  # ueberlappt best
        other = make_moment(300, 340, title="other")
        clips = plan_clips(self._ranked(best, worse, other), 3600, cfg, None)
        titles = [c.title for c in clips]
        assert titles == ["best", "other"]

    def test_ranks_renumbered(self, cfg):
        best = make_moment(100, 150)
        worse = make_moment(140, 190)
        other = make_moment(300, 340)
        clips = plan_clips(self._ranked(best, worse, other), 3600, cfg, None)
        assert [c.rank for c in clips] == [1, 2]

    def test_edge_touching_clips_both_kept(self, cfg):
        a = make_moment(100, 150, punchline_t=-1)
        b = make_moment(150, 200, punchline_t=-1)
        clips = plan_clips(self._ranked(a, b), 3600, cfg, None)
        assert len(clips) == 2

    def test_overlays_clamped_into_clip(self, cfg):
        m = make_moment(
            100, 150,
            captions=[{"t": 20.0, "text": "zu frueh"}, {"t": 120.0, "text": "ok"}],
            zooms=[{"t": 500.0, "duration": 1.0}],
            sfx=[{"t": 90.0, "kind": "boom"}],
        )
        clips = plan_clips(self._ranked(m), 3600, cfg, None)
        c = clips[0]
        assert all(c.t0 <= cap["t"] <= c.t1 for cap in c.captions)
        assert all(c.t0 <= z["t"] <= c.t1 for z in c.zooms)
        assert all(c.t0 <= s["t"] <= c.t1 for s in c.sfx)

    def test_callback_refs_only_earlier_material(self, cfg):
        m = make_moment(
            1000, 1050,
            callback_refs=[{"t": 200.0, "note": "ok"}, {"t": 1020.0, "note": "im clip"},
                           {"t": 2000.0, "note": "zukunft"}],
        )
        clips = plan_clips(self._ranked(m), 3600, cfg, None)
        assert [r["t"] for r in clips[0].callback_refs] == [200.0]

    def test_clip_to_dict_complete(self, cfg):
        m = make_moment(100, 150, punchline_t=140)
        clips = plan_clips(self._ranked(m), 3600, cfg, None)
        d = clips[0].to_dict()
        for key in (
            "rank", "t0", "t1", "duration_s", "title", "category", "final_score",
            "semantic_score", "signal_score", "style", "channels", "punchline_t",
            "punchline_state", "reason", "captions", "zooms", "sfx",
            "callback_refs", "lore_refs", "source", "second_score",
        ):
            assert key in d

    def test_empty(self, cfg):
        assert plan_clips([], 3600, cfg, None) == []
