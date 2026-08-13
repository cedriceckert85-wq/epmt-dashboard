"""Reaction detection is pure numpy, so we test it with synthetic audio: a quiet
baseline with a couple of loud bursts (laughter/shouting) should surface as
ReactionEvents at the right times, and silence should surface nothing."""
import numpy as np

from clip_lab.reactions import detect_reactions


def _signal_with_bursts(sr, duration_s, burst_times, burst_len_s=0.5,
                        base=0.02, loud=0.7, seed=0):
    n = int(sr * duration_s)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n).astype("float32") * base
    for bt in burst_times:
        a = int(bt * sr)
        b = min(n, int((bt + burst_len_s) * sr))
        x[a:b] += rng.standard_normal(b - a).astype("float32") * loud
    return np.clip(x, -1, 1), sr


def test_detects_bursts_near_expected_times():
    x, sr = _signal_with_bursts(16000, 30.0, [5.0, 12.0, 22.0])
    evs = detect_reactions(x, sr, frame_ms=50, min_gap_s=2.0,
                           prominence=0.4, baseline_window_s=8.0)
    peaks = [e.t for e in evs]
    assert len(evs) >= 3
    for expected in (5.0, 12.0, 22.0):
        assert any(abs(p - expected) < 1.0 for p in peaks), (expected, peaks)


def test_silence_yields_nothing():
    x = np.zeros(16000 * 10, dtype="float32")
    evs = detect_reactions(x, 16000, frame_ms=50, prominence=0.5)
    assert evs == []


def test_intensity_is_bounded():
    x, sr = _signal_with_bursts(16000, 20.0, [10.0], loud=1.0)
    evs = detect_reactions(x, sr, prominence=0.4)
    assert evs
    for e in evs:
        assert 0.0 <= e.intensity <= 1.0


def test_min_gap_merges_close_peaks():
    # two bursts 0.5s apart should merge under a 2s min gap
    x, sr = _signal_with_bursts(16000, 20.0, [10.0, 10.5])
    evs = detect_reactions(x, sr, min_gap_s=2.0, prominence=0.4)
    close = [e for e in evs if 9.0 < e.t < 12.0]
    assert len(close) == 1


def test_higher_prominence_is_stricter():
    x, sr = _signal_with_bursts(16000, 30.0, [5.0, 15.0, 25.0], loud=0.3)
    lenient = detect_reactions(x, sr, prominence=0.2)
    strict = detect_reactions(x, sr, prominence=0.95)
    assert len(strict) <= len(lenient)


def test_empty_input_is_safe():
    assert detect_reactions(np.zeros(0, dtype="float32"), 16000) == []
