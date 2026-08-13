"""Bootstrap (F14): venv anlegen, Abhaengigkeiten installieren, doctor,
selftest — ein Befehl, idempotent, klare Ausgaben.

    python bootstrap.py            # alles
    python bootstrap.py --no-pip   # ohne Paket-Installation (offline)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_DIR = HERE / ".venv"
DEPS = ["numpy", "faster-whisper"]


def say(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(argv: list[str]) -> int:
    say("  $ " + " ".join(str(a) for a in argv))
    try:
        return subprocess.call([str(a) for a in argv], cwd=str(HERE))
    except OSError as exc:
        say(f"  Fehler: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="LoL Clip Lab Bootstrap")
    parser.add_argument("--no-pip", action="store_true",
                        help="pip-Installation ueberspringen (offline)")
    args = parser.parse_args()

    say("== LoL Clip Lab Bootstrap ==")
    if sys.version_info < (3, 11):
        say(f"Python {sys.version.split()[0]} gefunden — bitte Python 3.11+ installieren.")
        return 1

    py = venv_python()
    if py.is_file():
        say(f"[1/4] venv vorhanden: {VENV_DIR}")
    else:
        say(f"[1/4] Lege venv an: {VENV_DIR}")
        try:
            venv.EnvBuilder(with_pip=True).create(str(VENV_DIR))
        except (OSError, subprocess.CalledProcessError) as exc:
            say(f"venv fehlgeschlagen ({exc}) — nutze das System-Python weiter.")
            py = Path(sys.executable)

    if args.no_pip:
        say("[2/4] Paket-Installation uebersprungen (--no-pip).")
    else:
        say("[2/4] Installiere Abhaengigkeiten (numpy, faster-whisper) ...")
        rc = run([py, "-m", "pip", "install", "--upgrade", *DEPS])
        if rc != 0:
            say("  pip schlug fehl (kein Netz?) — weiter; --transcript geht auch ohne Whisper.")

    # Interpreter waehlen, der numpy hat (frische venv ohne Netz -> System-Python)
    def has_numpy(exe: Path) -> bool:
        try:
            return subprocess.call(
                [str(exe), "-c", "import numpy"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) == 0
        except OSError:
            return False

    if not has_numpy(py) and has_numpy(Path(sys.executable)):
        say("  Hinweis: venv hat kein numpy — nutze das System-Python.")
        py = Path(sys.executable)

    say("[3/4] Umgebungs-Check (doctor) ...")
    run([py, "-m", "cliplab", "doctor"])

    say("[4/4] Offline-Selbsttest ...")
    rc = run([py, "-m", "cliplab", "selftest"])
    if rc == 0:
        say("")
        say("Alles bereit. VOD analysieren mit:")
        say(f"  {py} -m cliplab analyze DEINE_VOD.mkv")
    return rc


if __name__ == "__main__":
    sys.exit(main())
