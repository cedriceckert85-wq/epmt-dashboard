"""F15: Selftest — hermetisch, deterministisch, beruehrt nichts Echtes."""

from __future__ import annotations

import json
import subprocess

import pytest

from cliplab.selftest import DemoLLM, load_demo_parts, run_selftest

quiet = lambda s: None  # noqa: E731


class TestSelftest:
    def test_runs_green(self, tmp_path):
        assert run_selftest(tmp_path / "st", log=quiet) == 0

    def test_outputs_exist(self, tmp_path):
        run_selftest(tmp_path / "st", log=quiet)
        for session in ("session1", "session2"):
            base = tmp_path / "st" / session
            for name in ("edit_sheet.md", "edit_plan.json", "clips.csv", "chapters.txt"):
                assert (base / name).is_file()

    def test_never_spawns_real_clis(self, tmp_path, monkeypatch):
        # Auch wenn claude/codex auf dem PATH liegen: kein einziger Spawn.
        def forbidden(*a, **k):
            raise AssertionError("Selftest darf NIE einen Prozess starten")

        monkeypatch.setattr(subprocess, "run", forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        monkeypatch.setattr(subprocess, "call", forbidden)
        assert run_selftest(tmp_path / "st", log=quiet) == 0

    def test_byte_deterministic(self, tmp_path):
        run_selftest(tmp_path / "a", log=quiet)
        run_selftest(tmp_path / "b", log=quiet)
        for session in ("session1", "session2"):
            for name in ("edit_sheet.md", "edit_plan.json", "clips.csv", "chapters.txt"):
                fa = (tmp_path / "a" / session / name).read_bytes()
                fb = (tmp_path / "b" / session / name).read_bytes()
                assert fa == fb, f"{session}/{name} nicht byte-deterministisch"

    def test_scratch_memory_not_real(self, tmp_path, monkeypatch):
        # Selftest schreibt sein Gedaechtnis NUR in den Scratch-Ordner
        monkeypatch.chdir(tmp_path)
        run_selftest(tmp_path / "st", log=quiet)
        assert (tmp_path / "st" / "memory.json").is_file()
        assert not (tmp_path / "cliplab_memory.json").exists()

    def test_gag_counter_2x_after_second_session(self, tmp_path):
        run_selftest(tmp_path / "st", log=quiet)
        brain = json.loads((tmp_path / "st" / "memory.json").read_text(encoding="utf-8"))
        gag = next(g for g in brain["gags"] if g["slug"] == "der_verfluchte_busch")
        assert gag["times_seen"] == 2

    def test_sheet2_has_lore_lines(self, tmp_path):
        run_selftest(tmp_path / "st", log=quiet)
        sheet2 = (tmp_path / "st" / "session2" / "edit_sheet.md").read_text(encoding="utf-8")
        assert "🧠 Lore" in sheet2 and "(2x gesehen)" in sheet2

    def test_style_demo_cut_as(self, tmp_path):
        run_selftest(tmp_path / "st", log=quiet)
        sheet1 = (tmp_path / "st" / "session1" / "edit_sheet.md").read_text(encoding="utf-8")
        assert "Cut as: insta_funny" in sheet1

    def test_chapters_first_line_00_00(self, tmp_path):
        run_selftest(tmp_path / "st", log=quiet)
        chapters = (tmp_path / "st" / "session1" / "chapters.txt").read_text(encoding="utf-8")
        assert chapters.startswith("00:00 ")

    def test_independent_of_user_config_renames(self, tmp_path, monkeypatch):
        # User benennt in seiner config.toml alle Kanaele um — Selftest
        # nutzt Code-Defaults und bleibt gruen.
        config = tmp_path / "config.toml"
        config.write_text(
            '[[channels]]\nname = "voellig_anders"\n', encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        assert run_selftest(tmp_path / "st", log=quiet) == 0

    def test_no_ffmpeg_needed(self, tmp_path, monkeypatch):
        import cliplab.media as media

        monkeypatch.setattr(media, "have_ffmpeg", lambda which=None: None)
        monkeypatch.setattr(media, "have_ffprobe", lambda which=None: None)
        assert run_selftest(tmp_path / "st", log=quiet) == 0


class TestDemoLLM:
    def test_chatty_but_extractable(self):
        responses = {"s": {"session": {"summary": "x"}, "moments": {"moments": []}}}
        llm = DemoLLM("s", responses)
        from cliplab.editorial import SESSION_MARKER
        from cliplab.jsonextract import extract_json

        out = llm(SESSION_MARKER + "\nrest")
        assert "```" in out  # geschwaetzig
        assert extract_json(out) == {"summary": "x"}

    def test_unknown_prompt_none(self):
        llm = DemoLLM("s", {})
        assert llm("voellig anderer prompt") is None

    def test_fixtures_load(self):
        parts = load_demo_parts("x.mkv")
        assert parts.duration == 3600.0
        assert len(parts.segments) > 30
        assert len(parts.reactions) == 5
        assert len(parts.events) == 4
        # Fixture enthaelt den Gag mit Aufloesung
        text = " ".join(s.text for s in parts.segments)
        assert "VERFLUCHT" in text and "PENTAKILL" in text
