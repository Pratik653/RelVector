"""Create one isolated virtual environment per external validator for benchmarking.

Usage::

    python scripts/setup_external_adapters.py                # all tools
    python scripts/setup_external_adapters.py sql-guardrail  # one tool

Environments are created under ``.venvs/<tool>`` (git-ignored) with pinned versions from
``sqlguard_ninja.benchmarking.adapters.EXTERNAL_TOOLS``. The tools are installed as ordinary
dependencies; no third-party code is copied into this repository.
"""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

from sqlguard_ninja.benchmarking.adapters import EXTERNAL_TOOLS

ROOT = Path(__file__).resolve().parents[1]


def interpreter(env: Path) -> Path:
    return env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def setup(name: str) -> Path:
    tool = EXTERNAL_TOOLS[name]
    env = ROOT / ".venvs" / name
    if not interpreter(env).exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(env)
    py = interpreter(env)
    subprocess.run([str(py), "-m", "pip", "install", "-q", tool.pip_spec], check=True)
    print(f"{name}: {py}")
    return py


def main() -> int:
    names = sys.argv[1:] or list(EXTERNAL_TOOLS)
    for name in names:
        if name not in EXTERNAL_TOOLS:
            print(f"unknown tool {name!r}; choose from {sorted(EXTERNAL_TOOLS)}", file=sys.stderr)
            return 2
        setup(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
