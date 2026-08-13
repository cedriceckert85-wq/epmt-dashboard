from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cliplab.config import Config  # noqa: E402
from cliplab.editorial import Moment  # noqa: E402
from cliplab.transcribe import TranscriptSegment  # noqa: E402


@pytest.fixture
def cfg() -> Config:
    return Config()


def make_segment(t0: float, t1: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(t0=t0, t1=t1, text=text)


def make_moment(t0: float, t1: float, **kw) -> Moment:
    defaults = dict(title=f"M{t0}", category="funny", score=5.0)
    defaults.update(kw)
    return Moment(t0=t0, t1=t1, **defaults)


class FakeRunner:
    """Injizierbarer LLM-Fake: liefert Antworten der Reihe nach oder per Marker."""

    def __init__(self, responses=None, by_marker=None):
        self.responses = list(responses or [])
        self.by_marker = dict(by_marker or {})
        self.prompts: list[str] = []

    def __call__(self, prompt: str):
        self.prompts.append(prompt)
        for marker, resp in self.by_marker.items():
            if marker in prompt:
                return resp
        if self.responses:
            return self.responses.pop(0)
        return None


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_run(returncode=0, stdout="", stderr="", record=None):
    def _run(argv, **kwargs):
        if record is not None:
            record.append((list(argv), kwargs))
        return FakeProc(returncode, stdout, stderr)

    return _run
