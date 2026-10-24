"""Translate a SQLGuard Ninja policy + role into the simpler models of external validators.

External tools have no roles or classification labels. The translation is deliberately
*conservative* and documented, so the comparison is about enforcement quality and not about
a hostile translation:

* granted tables → table allowlist;
* granted columns whose labels resolve to ``allow`` → column allowlist;
* columns that are ungranted or whose labels resolve to anything else (deny, aggregate-only,
  review) → column denylist (the external models cannot express aggregate-only or review);
* tenant column of a tenant-scoped table → required equality predicate with the context value.
"""

from __future__ import annotations

from typing import Any

from sqlguard_ninja.policy.model import Access, Policy
from sqlguard_ninja.privacy.rules import resolve_column_access


def translate_for_role(policy: Policy, role_name: str | None, dialect: str) -> dict[str, Any]:
    """Return a JSON-serialisable, tool-neutral description of what ``role_name`` may read."""
    _, role = policy.role(role_name)
    tables: dict[str, Any] = {}
    denied_names: set[str] = set()
    for tname, tdef in policy.catalog.tables.items():
        grant = role.tables.get(tname) if role is not None else None
        if role is not None and grant is None:
            denied_names.update(c for c in tdef.columns)
            continue
        allowed, denied = [], []
        for cname in tdef.columns:
            listed = grant is None or grant.columns == "*" or cname in grant.columns
            if grant is not None and cname in grant.deny_columns:
                listed = False
            access = resolve_column_access(policy, role, tname, cname).strongest
            if listed and access is Access.ALLOW:
                allowed.append(cname)
            else:
                denied.append(cname)
        tenant_scoped = role is None or role.tenant_scoped
        tables[tname] = {
            "allow_columns": allowed,
            "deny_columns": denied,
            "tenant_column": tdef.tenant_column if tenant_scoped else None,
            "large": (tdef.estimated_rows or 0) >= policy.cost.large_table_rows,
        }
        denied_names.update(denied)
    allowed_anywhere = {c for t in tables.values() for c in t["allow_columns"]}
    limits = policy.effective_limits(role)
    return {
        "dialect": dialect,
        "tables": tables,
        # Name-only denylists cannot be table-scoped; a name that is allowed on some granted
        # table is not denylisted (avoids penalising a tool for a translation artefact).
        "pii_denylist": sorted(denied_names - allowed_anywhere),
        "tenant_context_key": policy.tenant.context_key,
        "limits": {
            "max_joins": limits.max_joins,
            "max_subquery_depth": limits.max_subquery_depth,
            "max_limit": limits.max_limit,
        },
    }
