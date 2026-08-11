import os, sys, pytest
from orchestrator.process_runner import ProcessRunner

@pytest.mark.skipif(os.name=="nt", reason="POSIX path; Windows tree-kill has its own harness spec")
def test_timeout_returns_fail_closed_result_quickly():
    r=ProcessRunner().run([sys.executable,"-c","import time;time.sleep(60)"],
                          cwd=".", timeout_s=1, env=os.environ.copy())
    assert r.timed_out and r.duration_s < 20
    assert r.exit_code != 0

def test_success_passthrough():
    r=ProcessRunner().run([sys.executable,"-c","print('ok')"],
                          cwd=".", timeout_s=10, env=os.environ.copy())
    assert r.exit_code==0 and not r.timed_out and "ok" in r.stdout
