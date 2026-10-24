"""Table and column grants.

Unknown and ungranted objects produce the *same* agent-facing message, so a caller cannot use
the guard to discover which tables exist.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlguard_ninja.core.findings import Action, Category, Finding, Severity
from sqlguard_ninja.core.rules.base import RuleContext
from sqlguard_ninja.core.rules.catalog import is_system_object


class TableAccessRule:
    rule_ids = ("table.not_permitted",)

    def check(self, ctx: RuleContext) -> Iterator[Finding]:
        catalog = ctx.policy.catalog
        seen: set[str] = set()
        for ref in ctx.analysis.tables:
            if ref.is_function or is_system_object(ref.name, ref.schema):
                continue  # handled by the function and catalog rules
            if ref.qualified in seen:
                continue
            seen.add(ref.qualified)
            message = f"The {ctx.name('table', ref.name)} is not available to this role."
            schema_ok = ref.schema is None or ref.schema == catalog.default_schema
            if ref.name not in catalog.tables or not schema_ok:
                yield Finding(
                    rule_id="table.not_permitted",
                    category=Category.TABLE_ACCESS,
                    severity=Severity.HIGH,
                    action=ctx.policy.defaults.unknown_table_action,
                    message=message,
                    detail=f"table {ref.qualified} is not in the policy catalog",
                    table=ref.qualified,
                )
                continue
            if ctx.role is not None and ref.name not in ctx.role.tables:
                yield Finding(
                    rule_id="table.not_permitted",
                    category=Category.TABLE_ACCESS,
                    severity=Severity.HIGH,
                    action=Action.DENY,
                    message=message,
                    detail=f"role {ctx.role_name!r} has no grant on {ref.name}",
                    table=ref.name,
                )


class ColumnAccessRule:
    """Column grants, unresolved columns and ``*`` that cannot be expanded."""

    rule_ids = ("column.not_permitted", "column.unresolved", "column.star_unexpandable")

    def check(self, ctx: RuleContext) -> Iterator[Finding]:
        catalog = ctx.policy.catalog
        defaults = ctx.policy.defaults
        seen: set[tuple[str, str]] = set()
        for ref in ctx.analysis.columns:
            key = (ref.table, ref.column)
            if key in seen:
                continue
            table = catalog.tables.get(ref.table)
            if table is None:
                continue  # the table rule already reported it
            grant = ctx.role.tables.get(ref.table) if ctx.role is not None else None
            if ctx.role is not None and grant is None:
                continue  # ungranted table: reported once by the table rule
            col_msg = ctx.name("column", f"{ref.table}.{ref.column}")
            star_hint = (
                " The query selects all columns; list only the columns you need."
                if ref.whole_row
                else ""
            )
            if ref.column not in table.columns:
                seen.add(key)
                yield Finding(
                    rule_id="column.not_permitted",
                    category=Category.COLUMN_ACCESS,
                    severity=Severity.MEDIUM,
                    action=defaults.unresolved_column_action,
                    message=f"The {col_msg} is not available to this role.",
                    detail="column not in catalog",
                    table=ref.table,
                    column=ref.column,
                )
                continue
            if grant is None:
                continue
            listed = grant.columns == "*" or ref.column in grant.columns
            if not listed or ref.column in grant.deny_columns:
                seen.add(key)
                yield Finding(
                    rule_id="column.not_permitted",
                    category=Category.COLUMN_ACCESS,
                    severity=Severity.HIGH,
                    action=Action.DENY,
                    message=f"The {col_msg} is not available to this role.{star_hint}",
                    detail=f"role {ctx.role_name!r} grant excludes this column",
                    table=ref.table,
                    column=ref.column,
                )

        for name in sorted(set(ctx.analysis.unresolved_columns)):
            yield Finding(
                rule_id="column.unresolved",
                category=Category.COLUMN_ACCESS,
                severity=Severity.MEDIUM,
                action=defaults.unresolved_column_action,
                message=(
                    "A column reference could not be attributed to a permitted table; "
                    "qualify columns with their table alias."
                ),
                detail=f"unresolved column {name}",
            )
        for star in sorted(set(ctx.analysis.unexpandable_stars)):
            yield Finding(
                rule_id="column.star_unexpandable",
                category=Category.COLUMN_ACCESS,
                severity=Severity.MEDIUM,
                action=defaults.unexpandable_star_action,
                message="SELECT * over a source without a known schema is not permitted.",
                detail=f"cannot expand {star}",
            )
