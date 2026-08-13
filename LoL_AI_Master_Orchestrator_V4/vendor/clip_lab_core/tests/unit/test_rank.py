"""Ranking blends the deterministic signal score with the LLM semantic score and
applies a per-10-minute cap so one busy stretch can't crowd out the rest."""
from clip_lab.config import Config
from clip_lab.models import Candidate
from clip_lab.rank import rank_candidates


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def cand(t0, signal=0.0, semantic=0.0):
    return Candidate(t0=t0, t1=t0 + 1, signal_score=signal, semantic_score=semantic)


def test_empty_returns_empty():
    assert rank_candidates([], cfg()) == []


def test_final_score_weights_are_applied():
    cands = [cand(0, signal=10, semantic=0), cand(100, signal=0, semantic=10)]
    ranked = rank_candidates(cands, cfg(w_signal=0.45, w_semantic=0.55, top_k=10))
    by_t = {c.t0: c.final_score for c in ranked}
    # normalized signal-only=0.45, semantic-only=0.55
    assert abs(by_t[0] - 0.45) < 1e-6
    assert abs(by_t[100] - 0.55) < 1e-6


def test_semantic_beats_signal_with_default_weights():
    cands = [cand(0, signal=10, semantic=0), cand(100, signal=0, semantic=10)]
    ranked = rank_candidates(cands, cfg(top_k=10))
    assert ranked[0].t0 == 100  # semantic-weighted higher


def test_top_k_limits_count():
    cands = [cand(i * 700, signal=i + 1) for i in range(20)]  # far apart buckets
    ranked = rank_candidates(cands, cfg(top_k=5, top_per_10min=10))
    assert len(ranked) == 5


def test_per_10min_cap_prevents_crowding():
    # 8 strong candidates all within the first 10 minutes
    cands = [cand(i * 30, signal=100 - i) for i in range(8)]
    ranked = rank_candidates(cands, cfg(top_k=100, top_per_10min=3))
    first_bucket = [c for c in ranked if c.t0 < 600]
    assert len(first_bucket) == 3


def test_output_sorted_by_score_desc():
    cands = [cand(0, semantic=1), cand(700, semantic=9), cand(1400, semantic=5)]
    ranked = rank_candidates(cands, cfg(top_k=10, top_per_10min=10))
    scores = [c.final_score for c in ranked]
    assert scores == sorted(scores, reverse=True)


def test_deterministic_repeatable():
    cands = [cand(i * 100, signal=i, semantic=(20 - i)) for i in range(10)]
    a = [c.t0 for c in rank_candidates(list(cands), cfg())]
    b = [c.t0 for c in rank_candidates(list(cands), cfg())]
    assert a == b
