"""The EDL stage turns ranked candidates into concrete, punchline-aware cut
points. This is where the 'edit intelligence' lives, so its rules are pinned:
comedy gets setup lead-in, clips end just after the punchline, lengths clamp to
sane bounds and to the media, overlays clamp into the clip, overlaps merge."""
from clip_lab.config import Config
from clip_lab.models import Candidate
from clip_lab.edl import build_edit_plan, _clip_bounds


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_funny_gets_more_preroll_than_clutch():
    c = cfg(funny_setup_preroll_s=6.0, default_preroll_s=2.0, clip_min_s=1.0)
    funny = Candidate(t0=100, t1=101, signal_score=1, category="funny")
    clutch = Candidate(t0=100, t1=101, signal_score=1, category="clutch")
    f0, _ = _clip_bounds(funny, c, duration=1000)
    c0, _ = _clip_bounds(clutch, c, duration=1000)
    assert f0 < c0  # funny starts earlier (more setup)


def test_clip_ends_shortly_after_punchline():
    c = cfg(punchline_decay_s=2.5, clip_min_s=1.0, default_postroll_s=3.0)
    cand = Candidate(t0=100, t1=101, signal_score=1, category="funny",
                     punchline_t=105.0)
    _, end = _clip_bounds(cand, c, duration=1000)
    assert abs(end - (105.0 + 2.5)) < 1e-6


def test_min_length_is_enforced():
    c = cfg(clip_min_s=8.0)
    cand = Candidate(t0=100, t1=100.5, signal_score=1, category="hype")
    t0, t1 = _clip_bounds(cand, c, duration=1000)
    assert t1 - t0 >= 8.0 - 1e-6


def test_max_length_is_enforced_keeping_end():
    c = cfg(clip_max_s=45.0)
    cand = Candidate(t0=100, t1=100, signal_score=1, category="funny",
                     punchline_t=300.0)  # far punchline -> long
    t0, t1 = _clip_bounds(cand, c, duration=1000)
    assert t1 - t0 <= 45.0 + 1e-6


def test_bounds_clamped_to_media():
    c = cfg(clip_min_s=8.0)
    cand = Candidate(t0=1.0, t1=2.0, signal_score=1, category="hype")
    t0, t1 = _clip_bounds(cand, c, duration=500)
    assert t0 >= 0.0
    cand2 = Candidate(t0=499.0, t1=505.0, signal_score=1, category="hype")
    _, t1b = _clip_bounds(cand2, c, duration=500)
    assert t1b <= 500.0


def test_overlapping_clips_merge():
    ranked = [
        Candidate(t0=100, t1=101, signal_score=1, category="hype",
                  final_score=0.9),
        Candidate(t0=102, t1=103, signal_score=1, category="hype",
                  final_score=0.5),  # overlaps the first after preroll/postroll
    ]
    plan = build_edit_plan(ranked, [], cfg(clip_min_s=8.0), duration=1000)
    assert len(plan) == 1
    assert plan[0].final_score == 0.9  # the stronger survives


def test_non_overlapping_clips_both_survive():
    ranked = [
        Candidate(t0=100, t1=101, signal_score=1, category="hype", final_score=0.9),
        Candidate(t0=500, t1=501, signal_score=1, category="hype", final_score=0.5),
    ]
    plan = build_edit_plan(ranked, [], cfg(clip_min_s=8.0), duration=1000)
    assert len(plan) == 2
    assert [p.rank for p in plan] == [1, 2]


def test_callback_inserts_only_reference_earlier_material():
    ranked = [Candidate(t0=500, t1=501, signal_score=1, category="funny",
                        final_score=0.9, callback_refs=[50.0, 600.0])]
    plan = build_edit_plan(ranked, [], cfg(), duration=1000)
    inserts = plan[0].callback_inserts
    # 50 is before the clip -> kept; 600 is after -> dropped
    assert len(inserts) == 1
    assert inserts[0]["ref_t0"] <= 50.0 <= inserts[0]["ref_t1"]


def test_overlays_clamped_into_clip():
    ranked = [Candidate(t0=100, t1=101, signal_score=1, category="funny",
                        final_score=0.9, punchline_t=104.0,
                        caption_suggestions=[{"t": 103.0, "text": "in"},
                                             {"t": 9999.0, "text": "out"}])]
    plan = build_edit_plan(ranked, [], cfg(clip_min_s=1.0), duration=1000)
    caps = plan[0].captions
    assert len(caps) == 1 and caps[0]["text"] == "in"


def test_ranks_are_renumbered_after_merge():
    ranked = [
        Candidate(t0=100, t1=101, signal_score=1, category="hype", final_score=0.3),
        Candidate(t0=500, t1=501, signal_score=1, category="hype", final_score=0.9),
    ]
    plan = build_edit_plan(ranked, [], cfg(clip_min_s=8.0), duration=1000)
    assert plan[0].rank == 1 and plan[0].final_score == 0.9
    assert plan[1].rank == 2
