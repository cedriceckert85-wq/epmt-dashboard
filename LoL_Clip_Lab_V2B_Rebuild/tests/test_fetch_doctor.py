"""F13: fetch (yt-dlp-Sicherheit) und doctor."""

from __future__ import annotations

import pytest

from cliplab.config import Config
from cliplab.doctor import run_doctor
from cliplab.errors import ClipLabError
from cliplab.fetchcmd import fetch, style_target_dir
from tests.conftest import FakeProc

quiet = lambda s: None  # noqa: E731


class TestStyleTargetDir:
    def test_none_is_root(self, tmp_path):
        assert style_target_dir(tmp_path, None) == tmp_path

    def test_channel_style_split(self, tmp_path):
        assert style_target_dir(tmp_path, "insta/funny") == tmp_path / "insta" / "funny"

    def test_backslash_accepted(self, tmp_path):
        assert style_target_dir(tmp_path, "insta\\funny") == tmp_path / "insta" / "funny"

    def test_traversal_rejected(self, tmp_path):
        with pytest.raises(ClipLabError):
            style_target_dir(tmp_path, "../etc")

    def test_pure_traversal_rejected(self, tmp_path):
        with pytest.raises(ClipLabError):
            style_target_dir(tmp_path, "../..")

    def test_dotted_style_slugged_inside_root(self, tmp_path):
        target = style_target_dir(tmp_path, "in.sta/fun.ny")
        assert target == tmp_path / "in_sta" / "fun_ny"

    def test_three_levels_rejected(self, tmp_path):
        with pytest.raises(ClipLabError):
            style_target_dir(tmp_path, "a/b/c")


class TestFetch:
    def _cfg(self, tmp_path):
        cfg = Config()
        cfg.base_dir = str(tmp_path)
        return cfg

    def test_missing_ytdlp_friendly(self, tmp_path):
        with pytest.raises(ClipLabError) as e:
            fetch(["http://x"], None, self._cfg(tmp_path), which=lambda n: None, log=quiet)
        assert "yt-dlp" in str(e.value)

    def test_no_urls(self, tmp_path):
        with pytest.raises(ClipLabError):
            fetch([], None, self._cfg(tmp_path), which=lambda n: "/bin/yt-dlp", log=quiet)

    def test_double_dash_separator_against_option_injection(self, tmp_path):
        records = []

        def run(argv, **kw):
            records.append(list(argv))
            return FakeProc(0)

        fetch(
            ["--exec=rm -rf /", "http://ok"],
            None,
            self._cfg(tmp_path),
            run_fn=run,
            which=lambda n: "/bin/yt-dlp",
            log=quiet,
        )
        argv = records[0]
        sep = argv.index("--")
        assert "--exec=rm -rf /" in argv[sep + 1 :]  # nur NACH dem Trenner

    def test_percent_escaped_in_outtmpl(self, tmp_path):
        percent_dir = tmp_path / "100% legal"
        cfg = Config()
        cfg.base_dir = str(percent_dir)
        records = []

        def run(argv, **kw):
            records.append(list(argv))
            return FakeProc(0)

        fetch(["http://ok"], None, cfg, run_fn=run, which=lambda n: "/bin/yt-dlp", log=quiet)
        outtmpl = records[0][records[0].index("-o") + 1]
        assert "100%% legal" in outtmpl
        assert "%(title)" in outtmpl  # Template-Teil bleibt un-escaped

    def test_rights_hint_printed(self, tmp_path):
        messages = []
        fetch(
            ["http://ok"],
            "insta/funny",
            self._cfg(tmp_path),
            run_fn=lambda a, **k: FakeProc(0),
            which=lambda n: "/bin/yt-dlp",
            log=messages.append,
        )
        assert any("Erlaubnis" in m for m in messages)

    def test_ytdlp_failure_friendly(self, tmp_path):
        with pytest.raises(ClipLabError) as e:
            fetch(
                ["http://x"],
                None,
                self._cfg(tmp_path),
                run_fn=lambda a, **k: FakeProc(1, stderr="ERROR: kaputt"),
                which=lambda n: "/bin/yt-dlp",
                log=quiet,
            )
        assert "kaputt" in str(e.value.message)


class TestDoctor:
    def test_all_present_exit0(self, cfg):
        rc = run_doctor(cfg, [], which=lambda n: f"/usr/bin/{n}", log=quiet)
        assert rc == 0

    def test_missing_ffmpeg_exit1(self, cfg):
        rc = run_doctor(cfg, [], which=lambda n: None, log=quiet)
        assert rc == 1

    def test_reports_are_honest(self, cfg):
        lines = []
        run_doctor(cfg, [], which=lambda n: None, log=lines.append)
        text = "\n".join(lines)
        assert "ffmpeg" in text and "FEHLT" in text
        assert "Signal-only" in text  # Degradation wird erklaert
        assert "einzig" in text.lower() or "EINZIGE" in text

    def test_model_download_hint(self, cfg):
        lines = []
        run_doctor(cfg, [], which=lambda n: f"/usr/bin/{n}", log=lines.append)
        assert any("einmalig" in line for line in lines)

    def test_second_cli_disabled_note(self, cfg):
        lines = []
        run_doctor(cfg, [], which=lambda n: f"/usr/bin/{n}", log=lines.append)
        assert any("deaktiviert" in line for line in lines)

    def test_second_cli_missing_silent_skip_note(self, cfg):
        cfg.llm2_cmd = ["codex", "exec", "-"]
        lines = []
        run_doctor(cfg, [], which=lambda n: None if n == "codex" else f"/usr/bin/{n}", log=lines.append)
        assert any("still uebersprungen" in line for line in lines)

    def test_config_warnings_shown(self, cfg):
        lines = []
        run_doctor(cfg, ["config: irgendwas kaputt"], which=lambda n: f"/usr/bin/{n}", log=lines.append)
        assert any("irgendwas kaputt" in line for line in lines)
