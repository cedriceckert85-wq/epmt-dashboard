"""Degradation ohne numpy: doctor + selftest laufen, Audio-Pfad meldet freundlich."""

from __future__ import annotations

import sys

import pytest

from cliplab.config import Config
from cliplab.doctor import run_doctor
from cliplab.errors import ClipLabError
from cliplab.media import read_wav_mono
from cliplab.selftest import run_selftest

quiet = lambda s: None  # noqa: E731


@pytest.fixture
def no_numpy(monkeypatch):
    """`import numpy` schlagfehl lassen (None in sys.modules)."""
    monkeypatch.setitem(sys.modules, "numpy", None)


class TestWithoutNumpy:
    def test_read_wav_friendly_error(self, tmp_path, no_numpy):
        with pytest.raises(ClipLabError) as e:
            read_wav_mono(tmp_path / "x.wav")
        assert "numpy" in str(e.value)

    def test_doctor_reports_missing_numpy(self, no_numpy):
        lines = []
        rc = run_doctor(Config(), [], which=lambda n: f"/usr/bin/{n}", log=lines.append)
        assert rc == 0  # numpy fehlt ist NICHT fatal
        assert any("numpy" in line and "FEHLT" in line for line in lines)

    def test_selftest_runs_without_numpy(self, tmp_path, no_numpy):
        # Kreativ-Pfad braucht kein numpy (kanned Reaktionen)
        assert run_selftest(tmp_path / "st", log=quiet) == 0

    def test_detect_reactions_needs_numpy_lazily(self, no_numpy):
        from cliplab.reactions import detect_reactions

        with pytest.raises(ImportError):
            detect_reactions([0.0] * 100, 16000)
