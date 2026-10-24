"""Structural limits: joins, nesting depth and LIMIT policy."""

from __future__ import annotations

from collections.abc import Iterator

from sqlguard_ninja.core.findings import Action, Category, Finding, Severity
from sqlguard_ninja.core.rules.base import RuleContext


class StructureLimitsRule:
    rule_ids = (
        "structure.max_joins",
        "structure.max_depth",
        "structure.limit_exceeded",
        "structure.limit_missing",
        "structure.limit_unparseable",
    )

    def check(self, ctx: RuleContext) -> Iterator[Finding]:
        a = ctx.analysis
        limits = ctx.limits
        if limits.max_joins is not None and a.join_count > limits.max_joins:
            yield Finding(
                rule_id="structure.max_joins",
                category=Category.STRUCTURE,
                severity=Severity.MEDIUM,
                action=Action.DENY,
                message=f"The query uses {a.join_count} joins; the limit is {limits.max_joins}.",
            )
        if limits.max_subquery_depth is not None and a.max_depth > limits.max_subquery_depth:
            yield Finding(
                rule_id="structure.max_depth",
                category=Category.STRUCTURE,
                severity=Severity.MEDIUM,
                action=Action.DENY,
                message=f"Subqueries are nested {a.max_depth} levels deep; the limit is "
                f"{limits.max_subquery_depth}.",
            )
        if not a.scopes:
            return
        root = a.scopes[-1]  # traverse_scope yields the root scope last
        if limits.max_limit is not None:
            for facts in a.scopes:
                if facts.limit_unparseable:
                    yield Finding(
                        rule_id="structure.limit_unparseable",
                        category=Category.STRUCTURE,
                        severity=Severity.MEDIUM,
                        action=Action.DENY,
                        message="LIMIT must be a numeric literal.",
                    )
                    break
                if facts.limit is not None and facts.limit > limits.max_limit:
                    yield Finding(
                        rule_id="structure.limit_exceeded",
                        category=Category.STRUCTURE,
                        severity=Severity.MEDIUM,
                        action=Action.DENY,
                        message=f"LIMIT {facts.limit} exceeds the maximum of {limits.max_limit}.",
                        remediation=f"Use LIMIT {limits.max_limit} or less.",
                    )
                    break
        if limits.require_limit and not root.has_limit:
            yield Finding(
                rule_id="structure.limit_missing",
                category=Category.STRUCTURE,
                severity=Severity.LOW,
                action=Action.DENY,
                message="The query must include a LIMIT clause.",
                remediation=f"Add LIMIT {limits.max_limit or 100}.",
            )
