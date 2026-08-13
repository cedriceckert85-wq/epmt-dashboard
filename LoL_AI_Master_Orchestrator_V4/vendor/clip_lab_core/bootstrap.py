#!/usr/bin/env python3
"""One-shot local setup for LoL Clip Lab.

Creates a .venv, installs requirements into it, then runs the offline self-test
so you can SEE the creative core produce an edit sheet before you point it at a
real VOD. Cross-platform (Windows / Linux / macOS). No network is used except
by pip when installing dependencies.

Usage:
    python bootstrap.py            # set up + self-test
    python bootstrap.py --no-venv  # install into the current interpreter
    python bootstrap.py --skip-install   # just run the self-test
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def _venv_python():
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kw)


def _check_python():
    v = sys.version_info
    print(f"[python] {sys.version.split()[0]} ({sys.executable})")
    if v < (3, 9):
        print("  ! Python 3.9+ required (3.11+ recommended so config.toml is read).")
        return False
    if v < (3, 11):
        print("  ~ Python < 3.11: config.toml will be ignored (built-in defaults are used).")
    return True


def _make_venv():
    if _venv_python().exists():
        print(f"[venv] reusing {VENV}")
        return True
    print(f"[venv] creating {VENV} …")
    r = _run([sys.executable, "-m", "venv", str(VENV)])
    if r.returncode != 0:
        print("  ! could not create the venv. Use --no-venv to install into the current Python.")
        return False
    return True


def _install(python):
    req = ROOT / "requirements.txt"
    print("[deps] installing requirements (numpy, faster-whisper) …")
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip"],
         stdout=subprocess.DEVNULL)
    r = _run([str(python), "-m", "pip", "install", "-r", str(req)])
    if r.returncode != 0:
        print("  ! dependency install failed. You can still run with --transcript if numpy is present.")
        return False
    return True


def _selftest(python):
    print("[selftest] running the editorial core on the bundled sample …")
    out = ROOT / "selftest_out"
    r = _run([str(python), "-m", "clip_lab", "selftest", "--out", str(out)],
             cwd=str(ROOT))
    if r.returncode == 0:
        print(f"\n[ok] Self-test passed. Open {out / 'edit_sheet.md'} to see the suggested cuts.")
    else:
        print("\n[!] Self-test did not pass — see the output above.")
    return r.returncode == 0


def _doctor(python):
    print("[doctor] checking local tooling (ffmpeg / whisper / LLM / AMD AMF) …")
    _run([str(python), "-m", "clip_lab", "doctor"], cwd=str(ROOT))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    use_venv = "--no-venv" not in argv
    do_install = "--skip-install" not in argv

    print("=== LoL Clip Lab — local setup ===")
    if not _check_python():
        return 1

    if use_venv:
        if not _make_venv():
            return 1
        python = _venv_python()
    else:
        python = Path(sys.executable)

    if do_install and not _install(python):
        # keep going: self-test only needs numpy, and may already be satisfied
        pass

    _doctor(python)
    ok = _selftest(python)

    print("\nNext:")
    if use_venv:
        if os.name == "nt":
            print(r"  .venv\Scripts\python -m clip_lab analyze C:\path\to\your_vod.mp4")
        else:
            print("  .venv/bin/python -m clip_lab analyze /path/to/your_vod.mp4")
    else:
        print("  python -m clip_lab analyze /path/to/your_vod.mp4")
    print("  (add --transcript my_transcript.json to skip whisper, --cut to also cut clips)")
    print("See README.md for the full workflow.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
