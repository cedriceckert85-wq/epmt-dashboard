#!/usr/bin/env python3
"""One-shot bootstrap for the LoL AI Master Orchestrator V4.

Run me once (via START.bat / start.sh). I am idempotent — run me again
any time to RESUME a stopped/blocked run.

Steps (stdlib only, no third-party imports):
  1. verify Python >= 3.10 and git
  2. create .venv and install pinned tool deps (pyyaml, pytest)
  3. git init + baseline commit (first run only)
  4. hand over to `python -m orchestrator run` inside the venv
"""
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
MIN_PY = (3, 10)


def fail(msg):
    print(f"\n[BOOTSTRAP-FEHLER] {msg}\n", file=sys.stderr)
    sys.exit(3)


def info(msg):
    print(f"[bootstrap] {msg}")


def venv_python():
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def check_python():
    if sys.version_info < MIN_PY:
        fail(f"Python {MIN_PY[0]}.{MIN_PY[1]}+ wird benötigt, gefunden: "
             f"{sys.version.split()[0]}. Bitte von https://python.org installieren.")


def check_git():
    try:
        subprocess.run(["git", "--version"], check=True,
                       capture_output=True, timeout=30)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        fail("git wurde nicht gefunden. Bitte installieren: https://git-scm.com/downloads")


def ensure_venv():
    py = venv_python()
    if not py.exists():
        info("Erzeuge virtuelle Umgebung .venv …")
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
        except Exception as e:
            # Debian/Ubuntu ship python3 without the venv/ensurepip module.
            # Remove the poisoned half-venv and give the correct instruction
            # instead of a misleading "check internet" later.
            import shutil
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            hint = ""
            if os.name != "nt":
                v = f"{sys.version_info.major}.{sys.version_info.minor}"
                hint = (f"\nAuf Debian/Ubuntu fehlt oft das venv-Modul. Installiere es mit:\n"
                        f"    sudo apt-get install -y python3-venv python{v}-venv python3-pip\n"
                        f"und starte danach erneut.")
            fail(f"Virtuelle Umgebung konnte nicht erstellt werden: {e}{hint}")
    if not py.exists():
        import shutil
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        fail("Virtuelle Umgebung unvollständig (kein Python im .venv). "
             "Bitte python3-venv installieren und START erneut ausführen.")
    req = ROOT / "requirements-bootstrap.txt"
    marker = VENV_DIR / ".deps-installed"
    if marker.exists() and marker.read_text() == req.read_text(encoding="utf-8"):
        return py
    info("Installiere Abhängigkeiten (pyyaml, pytest) …")
    for attempt in (1, 2, 3):
        r = subprocess.run([str(py), "-m", "pip", "install", "-q",
                            "--disable-pip-version-check", "-r", str(req)])
        if r.returncode == 0:
            marker.write_text(req.read_text(encoding="utf-8"))
            return py
        info(f"pip fehlgeschlagen (Versuch {attempt}/3) — erneuter Versuch …")
    fail("Abhängigkeiten konnten nicht installiert werden. Internetverbindung prüfen "
         "und START erneut ausführen.")


def ensure_git_repo():
    def git(*args, check=True):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=check)
    inside = git("rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        info("Initialisiere git-Repository …")
        git("init", "-b", "main")
    else:
        top = git("rev-parse", "--show-toplevel", check=False).stdout.strip()
        if top and Path(top).resolve() != ROOT.resolve():
            fail(f"Dieser Ordner liegt in einem fremden git-Repository ({top}). "
                 f"Bitte das Paket in einen eigenen, leeren Ordner entpacken.")
    for key, val in (("user.name", "LoL Orchestrator"),
                     ("user.email", "orchestrator@localhost")):
        if git("config", "--get", key, check=False).returncode != 0:
            git("config", key, val)
    if git("rev-parse", "HEAD", check=False).returncode != 0:
        info("Erzeuge Baseline-Commit …")
        git("add", "-A")
        git("commit", "-q", "-m", "V4 baseline (orchestrator package)")


def main():
    os.chdir(ROOT)
    print("=" * 64)
    print(" LoL AI Master Orchestrator V4 — One-Shot Bootstrap")
    print("=" * 64)
    check_python()
    check_git()
    py = ensure_venv()
    ensure_git_repo()

    env = dict(os.environ)
    bin_dir = str(py.parent)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(VENV_DIR)
    env.pop("PYTHONHOME", None)

    args = sys.argv[1:] or ["run"]
    if args and not args[0].startswith("-") and args[0] not in (
            "run", "status", "doctor", "approve", "unblock", "reset-phase"):
        args = ["run"] + args
    if args[0].startswith("-"):
        args = ["run"] + args

    info(f"Starte Orchestrator: python -m orchestrator {' '.join(args)}")
    r = subprocess.run([str(py), "-m", "orchestrator", *args], cwd=ROOT, env=env)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
