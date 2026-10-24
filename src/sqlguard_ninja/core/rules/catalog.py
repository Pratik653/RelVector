"""System-catalog and metadata access."""

from __future__ import annotations

from collections.abc import Iterator

from sqlguard_ninja.core.findings import Category, Finding, Severity
from sqlguard_ninja.core.rules.base import RuleContext

SYSTEM_SCHEMAS = frozenset(
    {"information_schema", "pg_catalog", "pg_toast", "mysql", "performance_schema", "sys"}
)
SYSTEM_TABLES = frozenset(
    {
        "sqlite_master",
        "sqlite_schema",
        "sqlite_temp_master",
        "sqlite_temp_schema",
        "sqlite_sequence",
        "sqlite_dbpage",
        "sqlite_stmt",
        "dbstat",
    }
)
SYSTEM_PREFIXES = ("pg_", "sqlite_", "pragma_")


def is_system_object(name: str, schema: str | None) -> bool:
    """True for catalog tables, views and table-valued pragma functions."""
    if schema and schema in SYSTEM_SCHEMAS:
        return True
    return name in SYSTEM_TABLES or name.startswith(SYSTEM_PREFIXES)


class SystemCatalogRule:
    """Deny reads of ``information_schema``, ``pg_catalog``, ``sqlite_master`` and similar.

    Catalog reads let an agent enumerate tables and columns it was never granted, and some
    catalog relations (``pg_shadow``, ``pg_authid``) expose credentials.
    """

    rule_ids = ("catalog.system_object",)

    def check(self, ctx: RuleContext) -> Iterator[Finding]:
        seen: set[str] = set()
        for ref in ctx.analysis.tables:
            name = ref.function_name if ref.is_function else ref.name
            if name is None or not is_system_object(name, ref.schema):
                continue
            if ref.qualified in seen:
                continue
            seen.add(ref.qualified)
            yield Finding(
                rule_id="catalog.system_object",
                category=Category.CATALOG,
                severity=Severity.HIGH,
                action=ctx.policy.defaults.catalog_access_action,
                message="Access to database system catalogs and metadata is not permitted.",
                detail=f"system object {ref.qualified}",
                table=ref.qualified,
            )
