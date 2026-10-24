"""Worker for krish2105/sqlguard (import name ``sqlguard``; installed from git, MIT)."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

exec((Path(__file__).parent / "_protocol.py").read_text(encoding="utf-8"))

from sqlguard import SqlGuard  # type: ignore[import-not-found]


def build(config: dict[str, Any]):  # type: ignore[no-untyped-def]
    allow = {name: set(t["allow_columns"]) for name, t in config["tables"].items()}
    guard = SqlGuard(allow, source_dialect=config["dialect"])

    def evaluate(sql, dialect, context, _config):  # type: ignore[no-untyped-def]
        report = guard.check(sql)
        return ("allow" if report.allowed else "deny"), list(report.errors)[:5]

    return evaluate


serve("sqlguard (krish2105)", version("sqlguard"), build)
