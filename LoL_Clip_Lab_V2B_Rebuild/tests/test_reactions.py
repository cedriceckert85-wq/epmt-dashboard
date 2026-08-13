"""F3: Reaktionserkennung — pure numpy, deterministisch, Pflicht-Invarianten."""

from __future__ import annotations

import numpy as np
import pytest

from cliplab.reactions import Reaction, detect_reactions

SR = 16000


def tone(duration_s: float, amp: float, freq: float = 220.0, sr: int = SR) -> np.ndarray:
    t = np.arange(int(duration_s * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def speech_like(duration_s: float, amp: float = 0.05, sr: int = SR, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sig = rng.normal(0.0, amp, int(duration_s * sr))
    return sig.astype(np.float64)


class TestInvariants:
    def test_empty_input_no_crash(self):
        assert detect_reactions(np.array([]), SR) == []

    def test_none_input(self):
        assert detect_reactions(None, SR) == []

    def test_silence_no_reactions(self):
        assert detect_reactions(np.zeros(SR * 60), SR) == []

    def test_muted_mic_tiny_noise_no_reactions(self):
        # weit unter -50 dBFS: absoluter Energie-Boden greift
        sig = speech_like(120, amp=0.0005)
        assert detect_reactions(sig, SR) == []

    def test_constant_hum_no_reactions(self):
        # konstanter Brumm ueber dem Floor: kollabierende Streuung darf
        # KEINE Reaktionen erzeugen (MAD-Floor)
        sig = tone(120, amp=0.05, freq=50.0)
        assert detect_reactions(sig, SR) == []

    def test_constant_loud_tone_no_reactions(self):
        sig = tone(120, amp=0.5, freq=440.0)
        assert detect_reactions(sig, SR) == []

    def test_burst_found_within_2s(self):
        # Sprachpegel-Baseline, ein +20-dB-Ausbruch bei t=60
        sig = speech_like(120, amp=0.02)
        burst = tone(2.0, amp=0.6, freq=300.0)
        start = int(60 * SR)
        sig[start : start + len(burst)] += burst
        found = detect_reactions(sig, SR)
        assert found, "Ausbruch nicht gefunden"
        assert any(abs(r.t - 61.0) <= 2.0 for r in found)

    def test_two_bursts_found(self):
        sig = speech_like(180, amp=0.02)
        for t_start in (40.0, 140.0):
            b = tone(1.5, amp=0.6)
            i = int(t_start * SR)
            sig[i : i + len(b)] += b
        found = detect_reactions(sig, SR)
        times = [r.t for r in found]
        assert any(abs(t - 40.7) <= 2.0 for t in times)
        assert any(abs(t - 140.7) <= 2.0 for t in times)

    def test_intensity_normalized_0_1(self):
        sig = speech_like(120, amp=0.02)
        b = tone(2.0, amp=0.9)
        sig[int(60 * SR) : int(60 * SR) + len(b)] += b
        for r in detect_reactions(sig, SR):
            assert 0.0 <= r.intensity <= 1.0

    def test_nearby_peaks_merged(self):
        sig = speech_like(120, amp=0.02)
        # zwei Ausbrueche nur 1s auseinander -> eine Region (merge_gap 2s)
        for t_start in (60.0, 61.5):
            b = tone(0.5, amp=0.6)
            i = int(t_start * SR)
            sig[i : i + len(b)] += b
        found = [r for r in detect_reactions(sig, SR) if 55 < r.t < 67]
        assert len(found) == 1

    def test_deterministic(self):
        sig = speech_like(90, amp=0.02, seed=3)
        b = tone(1.0, amp=0.7)
        sig[int(30 * SR) :][: len(b)] += b
        r1 = detect_reactions(sig, SR)
        r2 = detect_reactions(sig.copy(), SR)
        assert [(r.t, r.intensity) for r in r1] == [(r.t, r.intensity) for r in r2]


class TestInputVariants:
    def test_int16_input(self):
        sig = (speech_like(60, amp=0.02) * 32767).astype(np.int16)
        b = (tone(1.0, amp=0.6) * 32767).astype(np.int16)
        sig[int(30 * SR) :][: len(b)] = b
        found = detect_reactions(sig, SR)
        assert any(abs(r.t - 30.5) <= 2.0 for r in found)

    def test_stereo_input_averaged(self):
        mono = speech_like(60, amp=0.02)
        b = tone(1.0, amp=0.6)
        mono[int(30 * SR) :][: len(b)] += b
        stereo = np.stack([mono, mono], axis=-1)
        assert detect_reactions(stereo, SR)

    def test_nan_samples_no_crash(self):
        sig = speech_like(30, amp=0.02)
        sig[100:200] = np.nan
        detect_reactions(sig, SR)  # darf nicht crashen

    def test_very_short_input(self):
        assert detect_reactions(np.ones(10) * 0.5, SR) in ([], detect_reactions(np.ones(10) * 0.5, SR))

    def test_zero_samplerate(self):
        assert detect_reactions(np.ones(1000), 0) == []

    def test_region_bounds_ordered(self):
        sig = speech_like(60, amp=0.02)
        b = tone(1.0, amp=0.7)
        sig[int(20 * SR) :][: len(b)] += b
        for r in detect_reactions(sig, SR):
            assert r.t0 <= r.t <= r.t1


class TestThresholds:
    def test_small_bump_below_threshold_ignored(self):
        sig = speech_like(120, amp=0.02)
        # nur +4 dB: unter threshold_db=8
        b = tone(1.0, amp=0.032)
        sig[int(60 * SR) :][: len(b)] += b
        found = [r for r in detect_reactions(sig, SR) if 57 < r.t < 64]
        assert found == []

    def test_custom_threshold(self):
        sig = speech_like(120, amp=0.02)
        b = tone(1.0, amp=0.10)
        sig[int(60 * SR) :][: len(b)] += b
        strict = detect_reactions(sig, SR, threshold_db=20.0)
        assert [r for r in strict if 57 < r.t < 64] == []

    def test_floor_blocks_quiet_bursts(self):
        # Ausbruch, der absolut unter -50 dBFS bleibt -> nichts
        sig = speech_like(120, amp=0.00005)
        b = tone(1.0, amp=0.001)
        sig[int(60 * SR) :][: len(b)] += b
        assert detect_reactions(sig, SR) == []

    def test_reaction_dataclass_dict(self):
        r = Reaction(t=1.234, t0=1.0, t1=2.0, intensity=0.567)
        d = r.to_dict()
        assert d["t"] == 1.23 and d["intensity"] == 0.567
