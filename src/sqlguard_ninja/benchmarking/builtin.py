"""Locate the reference benchmark corpus and policy shipped with the package.

In a wheel, the files are packaged under ``sqlguard_ninja/_data/benchmarks``. In a source
checkout (editable install), they are read from the repository's ``benchmarks/`` directory.
"""

from __future__ import annotations

from pathlib import Path

_PACKAGE = Path(__file__).resolve().parents[1]
_CANDIDATES = (_PACKAGE / "_data" / "benchmarks", _PACKAGE.parents[1] / "benchmarks")

PREFIX = "builtin:"


def benchmarks_root() -> Path:
    for candidate in _CANDIDATES:
        if (candidate / "datasets").is_dir() and (candidate / "policies").is_dir():
            return candidate
    raise FileNotFoundError("the bundled benchmark data is missing from this installation")


def resolve(spec: str | Path, kind: str) -> Path:
    """Resolve ``builtin:<name>`` for ``kind`` 'dataset' or 'policy'; pass other paths through."""
    text = str(spec)
    if not text.startswith(PREFIX):
        return Path(text)
    name = text.removeprefix(PREFIX) or ("v1" if kind == "dataset" else "retail_saas")
    root = benchmarks_root()
    path = root / "datasets" / name if kind == "dataset" else root / "policies" / f"{name}.yaml"
    if not path.exists():
        available = sorted(
            p.name if kind == "dataset" else p.stem
            for p in (root / ("datasets" if kind == "dataset" else "policies")).iterdir()
            if not p.name.startswith(".")
        )
        raise FileNotFoundError(f"no built-in {kind} {name!r}; available: {available}")
    return path
