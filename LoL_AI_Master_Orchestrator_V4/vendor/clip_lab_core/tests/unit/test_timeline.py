"""signal_candidates is the deterministic safety net that must always yield
usable windows even with no LLM. We pin its clustering, event weighting and the
reaction co-occurrence boost."""
from clip_lab.config import Config
from clip_lab.models import GameEvent, ReactionEvent
from clip_lab.timeline import (build_timeline_doc, signal_candidates,
                               transcript_excerpt, _default_event_weight)
from clip_lab.models import TranscriptSegment


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_empty_inputs_give_no_candidates():
    assert signal_candidates([], [], cfg()) == []


def test_single_event_becomes_one_candidate():
    evs = [GameEvent(t=100.0, kind="penta")]
    cands = signal_candidates([], evs, cfg())
    assert len(cands) == 1
    assert cands[0].t0 == 100.0
    # penta default weight is high
    assert cands[0].signal_score >= 10.0


def test_events_far_apart_do_not_cluster():
    evs = [GameEvent(t=100.0, kind="kill"), GameEvent(t=500.0, kind="kill")]
    cands = signal_candidates([], evs, cfg(cluster_merge_gap_s=10.0))
    assert len(cands) == 2


def test_events_close_together_cluster():
    evs = [GameEvent(t=100.0, kind="kill"), GameEvent(t=105.0, kind="kill")]
    cands = signal_candidates([], evs, cfg(cluster_merge_gap_s=10.0))
    assert len(cands) == 1
    assert cands[0].t0 == 100.0 and cands[0].t1 == 105.0


def test_reaction_cooccurrence_boosts_event():
    ev = GameEvent(t=100.0, kind="kill")
    react = ReactionEvent(t=101.0, t0=100.5, t1=101.5, intensity=0.8)
    with_boost = signal_candidates([react], [ev],
                                   cfg(reaction_cooccurrence_window_s=8.0,
                                       reaction_cooccurrence_boost=2.0,
                                       cluster_merge_gap_s=10.0))
    without = signal_candidates([], [ev], cfg())
    # the co-located reaction should raise the cluster's score
    assert with_boost[0].signal_score > without[0].signal_score


def test_default_event_weights_ordering():
    assert _default_event_weight("penta") > _default_event_weight("triple")
    assert _default_event_weight("triple") > _default_event_weight("kill")
    assert _default_event_weight("unknown_kind") == 1.0
    assert _default_event_weight("death") < 0


def test_explicit_weight_overrides_default():
    evs = [GameEvent(t=10.0, kind="kill", weight=99.0)]
    cands = signal_candidates([], evs, cfg())
    assert cands[0].signal_score >= 99.0


def test_build_timeline_doc_is_sorted_and_tagged():
    segs = [TranscriptSegment(t0=5.0, t1=6.0, text="hello")]
    reacts = [ReactionEvent(t=2.0, t0=1.5, t1=2.5, intensity=0.5)]
    evs = [GameEvent(t=8.0, kind="penta")]
    doc = build_timeline_doc(segs, reacts, evs)
    lines = doc.splitlines()
    assert "REACTION" in lines[0]      # t=2 first
    assert "SPEECH" in lines[1]        # t=5 second
    assert "GAME: penta" in lines[2]   # t=8 last


def test_transcript_excerpt_selects_overlapping_segments():
    segs = [
        TranscriptSegment(t0=0.0, t1=5.0, text="before"),
        TranscriptSegment(t0=10.0, t1=15.0, text="inside window"),
        TranscriptSegment(t0=100.0, t1=105.0, text="after"),
    ]
    ex = transcript_excerpt(segs, 9.0, 16.0)
    assert "inside window" in ex
    assert "before" not in ex and "after" not in ex
