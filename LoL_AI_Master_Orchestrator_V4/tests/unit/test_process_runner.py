import os
import sys

import pytest

from orchestrator.process_runner import ProcessRunner


@pytest.mark.skipif(os.name == "nt", reason="POSIX kill path; Windows uses taskkill")
def test_timeout_returns_fail_closed_result_quickly():
    r = ProcessRunner().run([sys.executable, "-c", "import time;time.sleep(60)"],
                            cwd=".", timeout_s=1, env=os.environ.copy())
    assert r.timed_out and r.duration_s < 20
    assert r.exit_code != 0


def test_success_passthrough():
    r = ProcessRunner().run([sys.executable, "-c", "print('ok')"],
                            cwd=".", timeout_s=30, env=os.environ.copy())
    assert r.exit_code == 0 and not r.timed_out and "ok" in r.stdout


def test_missing_executable_fails_closed_not_crash():
    r = ProcessRunner().run(["definitely-not-a-real-cli-xyz", "--version"],
                            cwd=".", timeout_s=10, env=os.environ.copy())
    assert r.exit_code == 127 and not r.timed_out
    assert "failed to launch" in r.stderr


def test_resolve_argv_keeps_unknown_and_resolves_known():
    from orchestrator.process_runner import resolve_argv
    assert resolve_argv(["definitely-not-a-real-cli-xyz"])[0] == "definitely-not-a-real-cli-xyz"
    resolved = resolve_argv([sys.executable, "-V"])
    assert resolved[0] == sys.executable


def test_stdin_text_delivery():
    r = ProcessRunner().run([sys.executable, "-c", "import sys;print(sys.stdin.read())"],
                            cwd=".", timeout_s=30, env=os.environ.copy(),
                            stdin_text="hello-agent")
    assert r.exit_code == 0 and "hello-agent" in r.stdout
