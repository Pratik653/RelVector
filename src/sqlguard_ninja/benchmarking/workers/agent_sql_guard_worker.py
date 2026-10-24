"""Worker for sakura-sky/sql-guard (PyPI ``agent-sql-guard``, import name ``sql_guard``)."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

exec((Path(__file__).parent / "_protocol.py").read_text(encoding="utf-8"))

from sql_guard import PiiDenylist, SqlGuard, SqlGuardConfig  # type: ignore[import-not-found]

_OUTCOME = {"allow": "allow", "confirm": "review", "deny": "deny"}


def build(config: dict[str, Any]):  # type: ignore[no-untyped-def]
    guard = SqlGuard(
        SqlGuardConfig.from_settings(
            # Pass "substrings" explicitly: upstream from_mapping() defaults a missing key to
            # () and then rejects it as "not a list" (agent-sql-guard 0.2.0).
            pii_denylist=PiiDenylist.from_mapping(
                {"columns": config["pii_denylist"], "substrings": []}
            ),
            allowed_tables=list(config["tables"]),
            dialect=config["dialect"],
        )
    )

    def evaluate(sql, dialect, context, _config):  # type: ignore[no-untyped-def]
        # evaluate_static() returns CONFIRM ("awaiting cost evaluation") for every query that
        # passes the static rules; the cost stage needs a warehouse dry-run. This benchmark is
        # static, so supply a zero-byte dry-run and let only the static rules decide.
        decision = guard.evaluate(sql, bytes_processed=0)
        outcome = _OUTCOME.get(str(decision.outcome.value).lower(), "deny")
        return outcome, [decision.reason[:120]] if outcome != "allow" else []

    return evaluate


serve("agent-sql-guard", version("agent-sql-guard"), build)
