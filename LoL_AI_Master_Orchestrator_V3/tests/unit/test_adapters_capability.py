"""Provider adapter capability gating: no CLI flag is ever assumed, CLI
version drift fails closed, unavailable CLIs report themselves honestly."""
import os, stat, sys
from pathlib import Path

import pytest

from orchestrator.adapters.claude import ClaudeAdapter
from orchestrator.adapters.codex import CodexAdapter
from orchestrator.models import AgentRequest, AgentRole

POSIX = os.name != "nt"

CLAUDE_STUB = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "claude 2.5.0"; exit 0; fi
echo "usage: --print --output-format --permission-mode --disallowedTools"
exit 0
"""

CLAUDE_STUB_NO_FLAGS = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "claude 0.1.0"; exit 0; fi
echo "usage: nothing supported"
exit 0
"""


def _stub(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def _request(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("do things")
    return AgentRequest(run_id="r", phase_id="00", role=AgentRole.BUILDER,
                        workspace=tmp_path, prompt_file=prompt,
                        output_schema_file=Path("s.json"), timeout_s=10)


def test_missing_cli_reports_unavailable(tmp_path):
    a = ClaudeAdapter("definitely-not-a-real-cli-xyz")
    d = a.doctor()
    assert d["available"] is False
    r = a.run(_request(tmp_path))
    assert r.exit_code == 127 and r.structured is None   # fail closed

    c = CodexAdapter("definitely-not-a-real-cli-xyz")
    assert c.doctor()["available"] is False


@pytest.mark.skipif(not POSIX, reason="shell stub")
def test_version_drift_fails_closed(tmp_path):
    exe = _stub(tmp_path, "claude", CLAUDE_STUB)
    a = ClaudeAdapter(exe, pinned_version="9.9.9")
    d = a.doctor()
    assert d["available"] is True and d["pinned_ok"] is False
    r = a.run(_request(tmp_path))
    assert r.exit_code == 127                            # drift => never run


@pytest.mark.skipif(not POSIX, reason="shell stub")
def test_missing_flags_fail_closed(tmp_path):
    exe = _stub(tmp_path, "claude", CLAUDE_STUB_NO_FLAGS)
    a = ClaudeAdapter(exe)
    d = a.doctor()
    assert d["available"] is True and d["flags_ok"] is False
    r = a.run(_request(tmp_path))
    assert r.exit_code == 127                            # unverified => never run


@pytest.mark.skipif(not POSIX, reason="shell stub")
def test_capability_ok_stub_passes_doctor(tmp_path):
    exe = _stub(tmp_path, "claude", CLAUDE_STUB)
    a = ClaudeAdapter(exe, pinned_version="2.5.0")
    d = a.doctor()
    assert d["available"] and d["flags_ok"] and d["pinned_ok"]
