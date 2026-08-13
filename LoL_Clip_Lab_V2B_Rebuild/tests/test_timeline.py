"""Timeline-Dokument + zeilen-alignierte Chunks."""

from __future__ import annotations

from cliplab.events import GameEvent
from cliplab.reactions import Reaction
from cliplab.timeline import build_entries, chunk_text_lines, render_doc
from tests.conftest import make_segment


class TestEntries:
    def test_sorted_chronologically(self):
        entries = build_entries(
            [make_segment(50, 55, "spaeter"), make_segment(10, 15, "frueher")],
            [Reaction(t=30, t0=29, t1=31, intensity=0.8)],
            [GameEvent(t=20, kind="kill", weight=1.0)],
        )
        assert [e.t for e in entries] == [10, 20, 30, 50]

    def test_kinds_marked(self):
        entries = build_entries(
            [make_segment(10, 15, "hallo welt")],
            [Reaction(t=30, t0=29, t1=31, intensity=0.8)],
            [GameEvent(t=20, kind="penta", weight=5.0)],
        )
        talk, event, reaction = entries[0], entries[1], entries[2]
        assert "TALK:" in talk.line and "hallo welt" in talk.line
        assert "GAME-EVENT: penta" in event.line
        assert "REAKTION" in reaction.line and "0.80" in reaction.line

    def test_machine_time_tag(self):
        entries = build_entries([make_segment(83, 90, "x")], [], [])
        assert "t=83" in entries[0].line

    def test_doc_header(self):
        doc = render_doc(build_entries([], [], []), 3600, "vod.mkv")
        assert "vod.mkv" in doc and "1:00:00" in doc

    def test_empty_ok(self):
        assert build_entries([], [], []) == []


class TestChunking:
    def test_single_chunk(self):
        text = "a\nb\nc\n"
        assert chunk_text_lines(text, 1000) == [text]

    def test_line_aligned(self):
        lines = [f"zeile {i} " + "x" * 90 + "\n" for i in range(100)]
        text = "".join(lines)
        chunks = chunk_text_lines(text, 1000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.endswith("\n")
        assert "".join(chunks) == text  # NIE vorne abschneiden: alles da

    def test_nothing_lost_no_overlap(self):
        text = "\n".join(f"L{i}" for i in range(500)) + "\n"
        chunks = chunk_text_lines(text, 300)
        assert "".join(chunks) == text

    def test_oversized_line_hard_split(self):
        text = "x" * 5000 + "\n"
        chunks = chunk_text_lines(text, 2000)
        assert "".join(chunks) == text
        assert all(len(c) <= 2000 for c in chunks)

    def test_min_chunk_size_enforced(self):
        text = "abc\ndef\n"
        chunks = chunk_text_lines(text, 1)  # absurd klein -> min 1000
        assert chunks == [text]

    def test_empty_text(self):
        assert chunk_text_lines("", 1000) == [""]
