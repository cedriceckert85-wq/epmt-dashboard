"""F13: CLI-Verhalten — Exit-Codes, Flags, batch, memory, selftest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cliplab.cli import main


@pytest.fixture
def app(tmp_path):
    """Isolierte App-Umgebung: eigene config.toml, kein echtes Gedaechtnis,
    LLM-CLI zeigt auf ein nicht existierendes Binary (nie echte Spawns)."""
    config = tmp_path / "config.toml"
    config.write_text(
        '[llm]\nllm_cmd = ["cliplab_test_gibtsnicht"]\nllm2_cmd = []\n'
        f'[memory]\npath = "memory.json"\n'
        f'[styles]\nprofile_path = "style_profile.json"\n',
        encoding="utf-8",
    )
    return tmp_path


def transcript_file(tmp_path):
    p = tmp_path / "transcript.json"
    p.write_text(
        json.dumps(
            {
                "segments": [
                    {"t0": 10, "t1": 20, "text": "hallo welt"},
                    {"t0": 100, "t1": 110, "text": "grosser moment"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return p


def run_cli(app, *args):
    return main(["--config", str(app / "config.toml"), *args])


class TestExitCodes:
    def test_missing_vod_exit_2(self, app, capsys):
        rc = run_cli(app, "analyze", str(app / "gibtsnicht.mkv"))
        assert rc == 2
        assert "nicht gefunden" in capsys.readouterr().out

    def test_missing_plan_exit_2(self, app, tmp_path):
        vod = app / "v.mkv"
        vod.write_bytes(b"x")
        rc = run_cli(app, "cut", str(vod), str(app / "kein_plan.json"))
        assert rc == 2

    def test_operational_error_exit_1(self, app):
        vod = app / "v.mkv"
        vod.write_bytes(b"kein echtes video")
        plan = app / "plan.json"
        plan.write_text('{"kaputt": true}', encoding="utf-8")
        rc = run_cli(app, "cut", str(vod), str(plan))
        assert rc == 1

    def test_no_command_help_exit_2(self, app):
        assert run_cli(app) == 2

    def test_broken_config_warns_but_runs(self, tmp_path, capsys):
        config = tmp_path / "config.toml"
        config.write_text("[kaputt", encoding="utf-8")
        rc = main(["--config", str(config), "memory"])
        out = capsys.readouterr().out
        assert rc == 0 and "WARNUNG" in out


class TestAnalyze:
    def test_analyze_with_transcript_no_llm(self, app, capsys):
        vod = app / "session.mkv"
        vod.write_bytes(b"fake video")
        tr = transcript_file(app)
        rc = run_cli(app, "analyze", str(vod), "--transcript", str(tr), "--no-llm")
        assert rc == 0
        out_dir = app / "session_cliplab"
        assert (out_dir / "edit_sheet.md").is_file()
        assert (out_dir / "chapters.txt").is_file()
        sheet = (out_dir / "edit_sheet.md").read_text(encoding="utf-8")
        assert "Signal-only" in sheet

    def test_analyze_out_override(self, app):
        vod = app / "session.mkv"
        vod.write_bytes(b"fake")
        tr = transcript_file(app)
        rc = run_cli(
            app, "analyze", str(vod), "--transcript", str(tr),
            "--no-llm", "--out", str(app / "eigener_ordner"),
        )
        assert rc == 0
        assert (app / "eigener_ordner" / "edit_plan.json").is_file()

    def test_llm_cli_missing_falls_back_with_note(self, app, capsys):
        # llm_cmd zeigt auf nicht existierendes Binary -> Hinweis + Signal-only
        vod = app / "session.mkv"
        vod.write_bytes(b"fake")
        tr = transcript_file(app)
        rc = run_cli(app, "analyze", str(vod), "--transcript", str(tr))
        assert rc == 0
        assert "nicht gefunden" in capsys.readouterr().out


class TestBatch:
    def test_missing_folder_exit_2(self, app):
        assert run_cli(app, "batch", str(app / "kein_ordner")) == 2

    def test_empty_folder_exit_1(self, app):
        folder = app / "leer"
        folder.mkdir()
        assert run_cli(app, "batch", str(folder)) == 1

    def test_continues_after_failures_collective_exit(self, app, capsys):
        folder = app / "vods"
        folder.mkdir()
        (folder / "kaputt1.mkv").write_bytes(b"x")
        (folder / "kaputt2.mp4").write_bytes(b"y")
        rc = run_cli(app, "batch", str(folder), "--no-llm")
        out = capsys.readouterr().out
        assert rc == 1  # Sammel-Exit: Fehler gab es
        assert "kaputt1" in out and "kaputt2" in out  # beide versucht
        assert "weiter mit der naechsten" in out

    def test_batch_success_exit_0(self, app):
        folder = app / "vods"
        folder.mkdir()
        (folder / "a.mkv").write_bytes(b"fake")
        tr = transcript_file(app)
        rc = run_cli(app, "batch", str(folder), "--no-llm", "--transcript", str(tr))
        assert rc == 0


class TestMemoryCmd:
    def test_show_empty(self, app, capsys):
        rc = run_cli(app, "memory")
        assert rc == 0
        assert "0 Running Gags" in capsys.readouterr().out

    def test_clear_missing(self, app, capsys):
        rc = run_cli(app, "memory", "--clear")
        assert rc == 0
        assert "Kein Gedaechtnis" in capsys.readouterr().out

    def test_clear_existing(self, app, capsys):
        (app / "memory.json").write_text('{"gags": []}', encoding="utf-8")
        rc = run_cli(app, "memory", "--clear")
        assert rc == 0
        assert not (app / "memory.json").exists()

    def test_show_content(self, app, capsys):
        (app / "memory.json").write_text(
            json.dumps({"gags": [{"name": "Busch", "times_seen": 3}]}), encoding="utf-8"
        )
        run_cli(app, "memory")
        out = capsys.readouterr().out
        assert "Busch" in out and "3x" in out


class TestLearnCmd:
    def test_first_run_creates_structure(self, app, capsys):
        rc = run_cli(app, "learn", str(app / "references"))
        assert rc == 0
        assert (app / "references").is_dir()
        assert "Beispielstruktur" in capsys.readouterr().out

    def test_empty_structure_second_run(self, app, capsys):
        run_cli(app, "learn", str(app / "references"))
        rc = run_cli(app, "learn", str(app / "references"))
        assert rc == 0


class TestOtherCmds:
    def test_doctor_runs(self, app, capsys):
        rc = run_cli(app, "doctor")
        assert rc in (0, 1)
        assert "Umgebungs-Check" in capsys.readouterr().out

    def test_fetch_without_ytdlp(self, app, monkeypatch):
        monkeypatch.setattr("cliplab.fetchcmd.shutil.which", lambda n: None)
        # fetch nutzt injiziertes which nur intern — CLI-Pfad: yt-dlp fehlt -> Exit 1
        rc = run_cli(app, "fetch", "http://example.com/x")
        assert rc == 1

    def test_selftest_exit_0(self, app, tmp_path, capsys):
        rc = run_cli(app, "selftest", "--out", str(tmp_path / "st"))
        assert rc == 0
        assert "Selftest OK" in capsys.readouterr().out

    def test_version_flag(self, app):
        with pytest.raises(SystemExit) as e:
            run_cli(app, "--version")
        assert e.value.code == 0
