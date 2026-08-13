"""The editorial brain is the whole point of the tool, so its contract is pinned:
LLM moments must attach to the right candidates (including zero-width single-event
windows — the regression that motivated the _best_overlap fix), unmatched moments
become discovered windows, and every failure mode degrades to signal-only."""
from clip_lab.config import Config
from clip_lab.models import Candidate
from clip_lab.editorial import run_editorial, _apply_moments, _best_overlap
from clip_lab.llm_client import LLMClient


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_best_overlap_matches_zero_width_candidate():
    # single-event candidate windows are zero-width (t0 == t1); an LLM window
    # that contains that point must still match it.
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    match = _best_overlap(cands, 140.0, 165.0, used=set())
    assert match is cands[0]


def test_best_overlap_returns_none_when_window_misses():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    assert _best_overlap(cands, 200.0, 220.0, used=set()) is None


def test_apply_moments_refines_matched_candidate():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    moments = [{"t0": 140.0, "t1": 165.0, "category": "hype",
                "semantic_score": 8, "punchline_t": 152.0,
                "title": "First Blood", "why": "payoff",
                "captions": [{"t": 151.0, "text": "hi"}]}]
    out = _apply_moments(cands, moments, cfg())
    assert len(out) == 1                     # refined in place, not duplicated
    assert out[0].category == "hype"
    assert out[0].semantic_score == 8
    assert out[0].title == "First Blood"
    assert out[0].editorial_source == "llm"


def test_apply_moments_discovers_no_event_window():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    moments = [{"t0": 700.0, "t1": 730.0, "category": "funny",
                "semantic_score": 7, "title": "Talk moment", "why": "funny"}]
    out = _apply_moments(cands, moments, cfg())
    assert len(out) == 2                     # original + discovered
    discovered = [c for c in out if c.signal_score == 0.0]
    assert len(discovered) == 1
    assert discovered[0].category == "funny"
    assert "llm-discovered" in discovered[0].reasons


def test_apply_moments_rejects_bad_windows():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    moments = [
        {"t0": None, "t1": 10},              # missing t0
        {"t0": 50, "t1": 40},                # inverted
        "not a dict",
    ]
    out = _apply_moments(cands, moments, cfg())
    assert len(out) == 1                     # nothing applied, none discovered


def test_semantic_score_is_clamped():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    moments = [{"t0": 140, "t1": 165, "semantic_score": 999}]
    out = _apply_moments(cands, moments, cfg())
    assert out[0].semantic_score == 10       # clamped to [0,10]


def test_run_editorial_falls_back_when_no_llm():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    out, source, ctx = run_editorial(cands, "log", llm=None, cfg=cfg())
    assert source == "signal"
    assert out is cands


def test_run_editorial_falls_back_on_bad_moment_json():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    # session pass returns an object, moment pass returns junk -> signal-only
    def runner(prompt):
        if "CANDIDATE WINDOWS" in prompt:
            return "sorry no json"
        return '{"running_gags": []}'
    llm = LLMClient(["x"], runner=runner)
    out, source, ctx = run_editorial(cands, "log", llm=llm, cfg=cfg(use_llm=True))
    assert source == "signal"


def test_run_editorial_uses_llm_when_available():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    def runner(prompt):
        if "CANDIDATE WINDOWS" in prompt:
            return '[{"t0": 140, "t1": 165, "category": "hype", "title": "x"}]'
        return '{"running_gags": ["gag"]}'
    llm = LLMClient(["x"], runner=runner)
    out, source, ctx = run_editorial(cands, "log", llm=llm, cfg=cfg(use_llm=True))
    assert source == "llm"
    assert ctx.get("running_gags") == ["gag"]
    assert out[0].category == "hype"


def test_use_llm_false_forces_signal_even_if_available():
    cands = [Candidate(t0=150.0, t1=150.0, signal_score=3)]
    llm = LLMClient(["x"], runner=lambda p: '[]')
    out, source, ctx = run_editorial(cands, "log", llm=llm, cfg=cfg(use_llm=False))
    assert source == "signal"
