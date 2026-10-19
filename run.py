#!/usr/bin/env python3
"""One-command start: `python3 run.py` (or `python run.py` on Windows).

Creates a virtual environment in .venv on first run, installs Recruitly into it,
then starts the app. Extra arguments are passed through, e.g. `python3 run.py demo`.
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
BIN = VENV / ("Scripts" if os.name == "nt" else "bin")
PY = BIN / ("python.exe" if os.name == "nt" else "python")
STAMP = VENV / ".installed"


def main() -> int:
    if sys.version_info < (3, 10):
        print("Recruitly needs Python 3.10 or newer. Download it from https://www.python.org/downloads/")
        return 1
    if not PY.exists():
        print("First run: setting up a virtual environment in .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV)
    pyproject = ROOT / "pyproject.toml"
    if not STAMP.exists() or STAMP.stat().st_mtime < pyproject.stat().st_mtime:
        print("Installing dependencies (one time, about a minute) ...")
        subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "-e", str(ROOT)])
        STAMP.touch()
    os.chdir(ROOT)
    return subprocess.call([str(PY), "-m", "recruitly", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
