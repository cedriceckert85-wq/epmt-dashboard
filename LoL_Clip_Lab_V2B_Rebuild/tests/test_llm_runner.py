"""F5: LLM-CLI-Runner — which-Aufloesung, {prompt}, stdin, Timeout."""

from __future__ import annotations

import subprocess

import pytest

from cliplab.llm import CliLLM, resolve_cmd
from tests.conftest import FakeProc


def which_none(name):
    return None


def which_fake(name):
    return f"C:\\tools\\{name}.cmd"  # Windows-.cmd-Shim-Szenario


class TestResolve:
    def test_empty_cmd(self):
        assert resolve_cmd([], which=which_fake) is None

    def test_none_cmd(self):
        assert resolve_cmd(None, which=which_fake) is None

    def test_missing_executable(self):
        assert resolve_cmd(["claude", "-p"], which=which_none) is None

    def test_resolves_to_full_path(self):
        out = resolve_cmd(["claude", "-p"], which=which_fake)
        assert out == ["C:\\tools\\claude.cmd", "-p"]

    def test_blank_head(self):
        assert resolve_cmd(["", "-p"], which=which_fake) is None

    def test_non_list(self):
        assert resolve_cmd("claude -p", which=which_fake) is None


class TestRun:
    def test_stdin_mode(self):
        calls = []

        def run_fn(argv, **kw):
            calls.append((argv, kw))
            return FakeProc(0, stdout='{"ok": 1}')

        llm = CliLLM(["claude", "-p"], run_fn=run_fn, which=which_fake)
        out = llm("mein prompt")
        assert out == '{"ok": 1}'
        argv, kw = calls[0]
        assert argv[0].endswith("claude.cmd")
        assert kw["input"] == "mein prompt"

    def test_prompt_placeholder_mode(self):
        calls = []

        def run_fn(argv, **kw):
            calls.append((argv, kw))
            return FakeProc(0, stdout="ok")

        llm = CliLLM(["mycli", "--text", "{prompt}"], run_fn=run_fn, which=which_fake)
        llm("HALLO")
        argv, kw = calls[0]
        assert "HALLO" in argv
        assert kw["input"] is None

    def test_unavailable_returns_none(self):
        llm = CliLLM(["claude", "-p"], which=which_none)
        assert llm("x") is None
        assert llm.available() is False

    def test_available(self):
        llm = CliLLM(["claude", "-p"], which=which_fake)
        assert llm.available() is True

    def test_timeout_returns_none(self):
        def run_fn(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout", 1))

        llm = CliLLM(["claude", "-p"], run_fn=run_fn, which=which_fake, timeout_s=1)
        assert llm("x") is None

    def test_oserror_returns_none(self):
        def run_fn(argv, **kw):
            raise OSError("kaputt")

        llm = CliLLM(["claude", "-p"], run_fn=run_fn, which=which_fake)
        assert llm("x") is None

    def test_empty_stdout_returns_none(self):
        llm = CliLLM(
            ["claude", "-p"],
            run_fn=lambda a, **k: FakeProc(0, stdout="   "),
            which=which_fake,
        )
        assert llm("x") is None

    def test_nonzero_exit_with_output_still_used(self):
        # manche CLIs schreiben brauchbares JSON und exiten trotzdem != 0
        llm = CliLLM(
            ["claude", "-p"],
            run_fn=lambda a, **k: FakeProc(3, stdout='{"a":1}'),
            which=which_fake,
        )
        assert llm("x") == '{"a":1}'

    def test_timeout_passed_through(self):
        seen = {}

        def run_fn(argv, **kw):
            seen.update(kw)
            return FakeProc(0, stdout="ok")

        CliLLM(["c"], run_fn=run_fn, which=which_fake, timeout_s=77)("x")
        assert seen["timeout"] == 77

    def test_utf8_encoding_forced(self):
        seen = {}

        def run_fn(argv, **kw):
            seen.update(kw)
            return FakeProc(0, stdout="ok")

        CliLLM(["c"], run_fn=run_fn, which=which_fake)("x")
        assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
