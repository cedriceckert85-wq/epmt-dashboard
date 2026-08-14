"""Regressionstests fuer die 8 Findings des Review-Councils.

Kern-Szenario der Zahlen-Findings: ein 400-stelliges Integer-Literal ist
GUELTIGES JSON/TOML, aber float(10**400) wirft OverflowError.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cliplab.cli import main
from cliplab.config import Config, load_config
from cliplab.editorial import parse_moments_response
from cliplab.memory import BrainStore, fresh_brain
from cliplab.pipeline import Deps, SessionParts, run_creative_pipeline
from cliplab.sanitize import clean_str
from cliplab.util import finite
from tests.conftest import FakeRunner, make_segment

BIG = 10**400  # 401-stelliges Integer-Literal — gueltiges JSON
quiet = lambda s: None  # noqa: E731

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class TestFix1BigIntLiterals:
    def test_finite_big_int_no_overflow(self):
        assert finite(BIG, default=-1.0) == -1.0

    def test_finite_negative_big_int(self):
        assert finite(-BIG, default=-1.0) == -1.0

    def test_clean_str_big_int_no_overflow(self):
        assert clean_str(BIG) == ""

    def test_clean_str_big_int_default(self):
        assert clean_str(BIG, default="fallback") == "fallback"

    def test_parse_moments_400_digit_t0(self, cfg):
        raw = '{"moments":[{"t0":' + str(BIG) + ',"t1":5,"title":"x"},{"t0":1,"t1":5,"title":"ok"}]}'
        moments = parse_moments_response(raw, 100, set(), cfg)
        # kaputtes Moment verworfen, gutes ueberlebt, kein Crash
        assert [m.title for m in moments] == ["ok"]

    def test_cut_plan_400_digit_t0(self, tmp_path, cfg):
        from cliplab.cutting import cut_from_plan
        from tests.conftest import FakeProc

        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = tmp_path / "plan.json"
        plan.write_text(
            '{"clips":[{"t0":' + str(BIG) + ',"t1":5,"title":"boese"},'
            '{"t0":1,"t1":5,"title":"ok","rank":1}]}',
            encoding="utf-8",
        )

        def run(argv, **kw):
            exe = Path(argv[0]).name
            if exe == "ffprobe":
                return FakeProc(0, stdout="100.0\n")
            if "-encoders" in argv:
                return FakeProc(0, stdout=" V..... libx264\n")
            Path(argv[-1]).write_bytes(b"video")
            return FakeProc(0)

        ok, notes, errors = cut_from_plan(
            vod, plan, cfg, log=quiet, which=lambda n: f"/usr/bin/{n}", run_fn=run
        )
        assert ok == 1  # kein Crash, boeser Eintrag als kaputt uebersprungen
        assert any("uebersprungen" in n for n in notes)

    def test_big_int_in_score_and_punchline(self, cfg):
        raw = (
            '{"moments":[{"t0":1,"t1":5,"score":' + str(BIG)
            + ',"punchline_t":' + str(-BIG) + ',"title":"x"}]}'
        )
        m = parse_moments_response(raw, 100, set(), cfg)[0]
        assert 0 <= m.score <= 10 and m.punchline_t == -1.0


class TestFix2MemoryBigInt:
    def test_hostile_memory_big_int_fresh_brain(self, tmp_path, cfg):
        store = BrainStore(tmp_path / "memory.json", cfg)
        store.path.write_text(
            '{"gags":[{"name":"g","times_seen":' + str(BIG) + "}]}", encoding="utf-8"
        )
        brain = store.load()  # NIE ein Crash
        assert isinstance(brain, dict)
        # entweder bereinigt (Zaehler geklemmt) oder frisch — beides ok
        for gag in brain["gags"]:
            assert isinstance(gag["times_seen"], int)
            assert 1 <= gag["times_seen"] <= 1_000_000

    def test_load_guard_catches_any_exception(self, tmp_path, cfg, monkeypatch):
        store = BrainStore(tmp_path / "memory.json", cfg)
        store.path.write_text('{"gags": []}', encoding="utf-8")
        import cliplab.memory as memory_mod

        def boom(data, cfg):
            raise ValueError("simulierter Sanitize-Fehler")

        monkeypatch.setattr(memory_mod, "sanitize_brain", boom)
        assert store.load() == fresh_brain()


class TestFix3ConfigBigInt:
    def test_big_int_in_float_key_warns_defaults(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text(f"[llm]\ntimeout_s = {BIG}\n", encoding="utf-8")
        cfg, warnings = load_config(p)  # kein Crash beim Start
        assert cfg.llm_timeout_s == 240.0
        assert any("timeout_s" in w and "falschen Typ" in w for w in warnings)

    def test_big_int_reaction_threshold(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text(f"[reactions]\nthreshold_db = {BIG}\n", encoding="utf-8")
        cfg, warnings = load_config(p)
        assert cfg.reaction_threshold_db == 8.0 and warnings

    def test_cli_starts_despite_big_int_config(self, tmp_path, capsys):
        p = tmp_path / "config.toml"
        p.write_text(f"[llm]\ntimeout_s = {BIG}\n", encoding="utf-8")
        rc = main(["--config", str(p), "memory"])
        assert rc == 0
        assert "WARNUNG" in capsys.readouterr().out


class TestFix4DeepToml:
    def test_deeply_nested_array_warns_defaults(self, tmp_path):
        p = tmp_path / "config.toml"
        depth = 20000
        p.write_text("[general]\nx = " + "[" * depth + "]" * depth + "\n", encoding="utf-8")
        cfg, warnings = load_config(p)  # kein RecursionError nach aussen
        assert cfg.language == "auto"
        assert any("kaputt" in w for w in warnings)


class TestFix5CutExitCode:
    @pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg nicht installiert")
    def test_fully_out_of_range_plan_exit1_fehler_no_file(self, tmp_path, capsys):
        from cliplab.media import default_run

        vod = tmp_path / "kurz.mp4"
        proc = default_run(
            [shutil.which("ffmpeg"), "-y", "-v", "error",
             "-f", "lavfi", "-i", "color=c=black:s=160x120:d=3:r=5",
             "-c:v", "libx264", "-preset", "ultrafast", str(vod)],
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        plan = tmp_path / "plan.json"
        plan.write_text(
            json.dumps({"clips": [{"t0": 500, "t1": 540, "title": "weit weg", "rank": 1}]}),
            encoding="utf-8",
        )
        config = tmp_path / "config.toml"
        config.write_text('[llm]\nllm_cmd = ["gibtsnicht"]\n', encoding="utf-8")
        rc = main(["--config", str(config), "cut", str(vod), str(plan),
                   "--out", str(tmp_path / "clips")])
        out = capsys.readouterr().out
        assert rc == 1  # Fehler, nicht nur Hinweis
        assert "Fehler" in out
        assert not any((tmp_path / "clips").glob("*.mp4"))  # keine (leere) Datei

    def test_truncated_range_stays_note_exit0(self, tmp_path, cfg):
        from cliplab.cutting import cut_from_plan
        from tests.conftest import FakeProc

        vod = tmp_path / "v.mkv"
        vod.write_bytes(b"x")
        plan = tmp_path / "plan.json"
        plan.write_text('{"clips":[{"t0":90,"t1":150,"title":"lang","rank":1}]}', encoding="utf-8")

        def run(argv, **kw):
            if Path(argv[0]).name == "ffprobe":
                return FakeProc(0, stdout="100.0\n")
            if "-encoders" in argv:
                return FakeProc(0, stdout=" V..... libx264\n")
            Path(argv[-1]).write_bytes(b"video")
            return FakeProc(0)

        ok, notes, errors = cut_from_plan(
            vod, plan, cfg, log=quiet, which=lambda n: f"/usr/bin/{n}", run_fn=run
        )
        assert ok == 1 and errors == []  # gekuerzt = Hinweis, KEIN Fehler
        assert any("gekuerzt" in n for n in notes)


BAT = Path(__file__).resolve().parent.parent / "START.bat"


class TestFix6And7StartBat:
    def test_crlf_line_endings(self):
        data = BAT.read_bytes()
        assert b"\r\n" in data
        # KEINE nackten LF-Zeilenenden (GOTO/CALL-Label-Suche!)
        assert b"\n" not in data.replace(b"\r\n", b"")

    def test_gitattributes_pins_crlf(self):
        ga = (BAT.parent / ".gitattributes").read_text(encoding="utf-8")
        assert "*.bat" in ga and "eol=crlf" in ga

    def test_python_probe_with_py_launcher_fallback(self):
        text = BAT.read_text(encoding="utf-8")
        assert 'python -c ""' in text  # Probe (Store-Stub exitet != 0)
        assert "py -3" in text  # Fallback auf den py-Launcher
        assert "%PYCMD% bootstrap.py" in text  # Fallback wird auch genutzt

    def test_cmd_parser_traps_still_avoided(self):
        lines = BAT.read_text(encoding="utf-8").lower().splitlines()
        code = [ln for ln in lines if not ln.strip().startswith("rem")]
        # kein aktives enabledelayedexpansion (nur im Kommentar erwaehnt)
        assert not any("enabledelayedexpansion" in ln for ln in code)
        # keine if-Klammer-Bloecke: kein "if ... (" am Zeilenende
        for line in code:
            if line.strip().startswith("if "):
                assert not line.rstrip().endswith("(")

    def test_readme_mentions_path_checkbox(self):
        readme = (BAT.parent / "README.md").read_text(encoding="utf-8")
        assert "Add python.exe to PATH" in readme


class TestFix8HonestModeLine:
    def test_garbage_llm_mode_line_states_true_reason(self, tmp_path, cfg):
        parts = SessionParts(
            vod_name="v.mkv",
            duration=600.0,
            segments=[make_segment(10, 20, "hallo")],
        )
        deps = Deps(llm_primary=FakeRunner(responses=["muell"] * 5), log=quiet)
        res = run_creative_pipeline(cfg, parts, deps, tmp_path / "out")
        sheet = res.paths["sheet"].read_text(encoding="utf-8")
        assert "keine verwertbaren Momente" in sheet
        assert "keine LLM-CLI verfuegbar" not in sheet  # nicht der falsche Grund

    def test_no_cli_mode_line_unchanged(self, tmp_path, cfg):
        parts = SessionParts(vod_name="v.mkv", duration=600.0,
                             segments=[make_segment(10, 20, "hallo")])
        deps = Deps(llm_primary=None, log=quiet)
        res = run_creative_pipeline(cfg, parts, deps, tmp_path / "out")
        sheet = res.paths["sheet"].read_text(encoding="utf-8")
        assert "keine LLM-CLI verfuegbar" in sheet
