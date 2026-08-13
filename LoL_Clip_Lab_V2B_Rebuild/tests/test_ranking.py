"""F10: Ranking — Gewichte, Null-Summen, Cap, top_k-Skalierung."""

from __future__ import annotations

import pytest

from cliplab.config import Config
from cliplab.ranking import compute_top_k, rank_moments
from tests.conftest import make_moment


class TestScoring:
    def test_weights_applied(self, cfg):
        a = make_moment(10, 20, score=10.0, signal=0.0, title="sem")
        b = make_moment(100, 110, score=0.0, signal=1.0, title="sig")
        ranked = rank_moments([a, b], 3600, cfg)
        # w_semantic 0.55 > w_signal 0.45 -> semantisches Moment gewinnt
        assert ranked[0].title == "sem"
        assert ranked[0].final == pytest.approx(0.55)
        assert ranked[1].final == pytest.approx(0.45)

    def test_zero_sum_weights_guarded(self, cfg):
        cfg.w_signal = 0.0
        cfg.w_semantic = 0.0
        ranked = rank_moments([make_moment(10, 20, score=8, signal=1)], 3600, cfg)
        assert ranked  # keine Division durch 0

    def test_zero_signal_everywhere_guarded(self, cfg):
        moments = [make_moment(i * 100, i * 100 + 10, score=5, signal=0.0) for i in range(3)]
        ranked = rank_moments(moments, 3600, cfg)
        assert len(ranked) == 3  # max_signal == 0 -> norm 0, kein Crash

    def test_signal_normalized_by_max(self, cfg):
        a = make_moment(10, 20, score=0, signal=2.0)
        b = make_moment(100, 110, score=0, signal=1.0)
        ranked = rank_moments([a, b], 3600, cfg)
        assert ranked[0].final == pytest.approx(0.45)
        assert ranked[1].final == pytest.approx(0.225)

    def test_deterministic_stable_tiebreak(self, cfg):
        a = make_moment(200, 210, score=5, title="B")
        b = make_moment(100, 110, score=5, title="A")
        r1 = rank_moments([a, b], 3600, cfg)
        r2 = rank_moments([b, a], 3600, cfg)
        assert [m.title for m in r1] == [m.title for m in r2]
        assert r1[0].t0 == 100  # frueheres t0 gewinnt bei Gleichstand

    def test_ranks_assigned_1_n(self, cfg):
        moments = [make_moment(i * 100, i * 100 + 10, score=i) for i in range(5)]
        ranked = rank_moments(moments, 3600, cfg)
        assert [m.rank for m in ranked] == list(range(1, len(ranked) + 1))

    def test_duplicates_dont_burn_slots(self, cfg):
        cfg.min_clips = 2
        cfg.clips_per_hour = 2
        dup1 = make_moment(10, 20, score=9, title="dup")
        dup2 = make_moment(10, 20, score=9, title="dup2")
        other = make_moment(700, 710, score=5, title="other")
        ranked = rank_moments([dup1, dup2, other], 3600, cfg)
        titles = [m.title for m in ranked]
        assert "other" in titles  # Duplikat hat den Platz nicht verbrannt
        assert len([t for t in titles if t.startswith("dup")]) == 1


class TestCaps:
    def test_per_10min_cap(self, cfg):
        cfg.per_10min_cap = 2
        moments = [make_moment(100 + i * 20, 110 + i * 20, score=9 - i) for i in range(5)]
        moments.append(make_moment(2000, 2010, score=1, title="anderswo"))
        ranked = rank_moments(moments, 3600, cfg)
        bucket0 = [m for m in ranked if m.t0 < 600]
        assert len(bucket0) == 2
        assert any(m.title == "anderswo" for m in ranked)

    def test_top_k_scales_with_duration(self, cfg):
        # 4h-Stream != 12 Clips: 8 Clips/h -> 32
        assert compute_top_k(4 * 3600, cfg) == 32
        assert compute_top_k(3600, cfg) == 8

    def test_top_k_minimum(self, cfg):
        assert compute_top_k(60, cfg) == cfg.min_clips
        assert compute_top_k(0, cfg) == cfg.min_clips

    def test_top_k_limits_output(self, cfg):
        cfg.clips_per_hour = 2
        cfg.min_clips = 2
        cfg.per_10min_cap = 99
        moments = [make_moment(i * 30, i * 30 + 10, score=5) for i in range(20)]
        ranked = rank_moments(moments, 3600, cfg)
        assert len(ranked) == 2

    def test_empty_moments(self, cfg):
        assert rank_moments([], 3600, cfg) == []
