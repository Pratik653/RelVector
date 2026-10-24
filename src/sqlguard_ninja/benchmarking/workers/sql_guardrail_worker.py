"""Worker for nickusevich/sql-guardrail (import name ``sqlguard``). MIT licensed upstream."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

exec((Path(__file__).parent / "_protocol.py").read_text(encoding="utf-8"))

from sqlguard import Policy, verify  # type: ignore[import-not-found]


def build(config: dict[str, Any]):  # type: ignore[no-untyped-def]
    tables = []
    for name, t in config["tables"].items():
        entry: dict[str, Any] = {
            "name": name,
            "allow_columns": t["allow_columns"],
            "deny_columns": t["deny_columns"],
            "large": False,
        }
        if t["tenant_column"]:
            entry["require_predicate"] = [
                {"column": t["tenant_column"], "op": "=", "value": "${tenant_id}"}
            ]
        tables.append(entry)
    limits = {k: v for k, v in config["limits"].items() if v is not None}
    data = {
        "read_only": True,
        "tables": tables,
        "limits": {
            "max_joins": limits.get("max_joins", 10),
            "max_subquery_depth": limits.get("max_subquery_depth", 8),
            "max_limit_value": limits.get("max_limit", 10_000),
        },
    }
    policy = Policy.from_dict(data)

    def evaluate(sql, dialect, context, _config):  # type: ignore[no-untyped-def]
        ctx = {k: v for k, v in context.items() if v is not None}
        result = verify(sql, policy, context=ctx)
        return ("allow" if result.allowed else "deny"), [v.code.value for v in result.violations]

    return evaluate


serve("sql-guardrail", version("sql-guardrail"), build)
