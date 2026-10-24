"""Statement-shape rules: read-only enforcement and session-changing statements."""

from __future__ import annotations

from collections.abc import Iterator

from sqlglot import exp

from sqlguard_ninja.core.analysis import SESSION_NODE_TYPES, WRITE_NODE_TYPES
from sqlguard_ninja.core.findings import Action, Category, Finding, Severity
from sqlguard_ninja.core.rules.base import RuleContext

_MYSQL_FAMILY = {"mysql", "doris", "starrocks", "singlestore"}


class ReadOnlyStatementRule:
    """Only a single SELECT (or set operation of SELECTs) is permitted, with no writes inside.

    The check is an allowlist on the root statement plus a deny walk over the full tree, so
    data-modifying CTEs, ``SELECT ... INTO`` and row locks are caught wherever they appear.
    """

    rule_ids = (
        "statement.not_read_only",
        "statement.unsupported",
        "statement.write_in_query",
        "statement.select_into",
        "statement.locking",
        "statement.executable_comment",
    )

    def check(self, ctx: RuleContext) -> Iterator[Finding]:
        root = ctx.analysis.root
        if root is None:
            return
        if ctx.analysis.dialect in _MYSQL_FAMILY and "/*!" in ctx.analysis.sql:
            yield Finding(
                rule_id="statement.executable_comment",
                category=Category.STATEMENT,
                severity=Severity.CRITICAL,
                action=Action.DENY,
                message="MySQL executable comments (/*! ... */) are not permitted.",
                detail="The server executes the comment body; the parser treats it as a comment.",
            )
        if isinstance(root, exp.Command):
            keyword = str(root.this).split()[0].upper() if root.this else "UNKNOWN"
            yield Finding(
                rule_id="statement.unsupported",
                category=Category.STATEMENT,
                severity=Severity.HIGH,
                action=Action.DENY,
                message="This statement type is not supported; only SELECT queries are allowed.",
                detail=f"unparsed command starting with {keyword}",
            )
            return
        if not isinstance(root, (exp.Select, exp.SetOperation)):
            yield Finding(
                rule_id="statement.not_read_only",
                category=Category.STATEMENT,
                severity=Severity.CRITICAL,
                action=Action.DENY,
                message="Only read-only SELECT queries are allowed.",
                detail=f"statement type {type(root).__name__}",
            )
            return

        reported: set[str] = set()
        for node in root.walk():
            if isinstance(node, (*WRITE_NODE_TYPES, *SESSION_NODE_TYPES, exp.Command)):
                key = type(node).__name__
                if key in reported:
                    continue
                reported.add(key)
                yield Finding(
                    rule_id="statement.write_in_query",
                    category=Category.STATEMENT,
                    severity=Severity.CRITICAL,
                    action=Action.DENY,
                    message="The query contains a write or session-changing statement.",
                    detail=f"{key} nested inside a SELECT (e.g. a data-modifying CTE)",
                )
            elif isinstance(node, exp.Into) and "into" not in reported:
                reported.add("into")
                yield Finding(
                    rule_id="statement.select_into",
                    category=Category.STATEMENT,
                    severity=Severity.CRITICAL,
                    action=Action.DENY,
                    message="SELECT ... INTO creates a table and is not permitted.",
                )
            elif isinstance(node, exp.Lock) and "lock" not in reported:
                reported.add("lock")
                yield Finding(
                    rule_id="statement.locking",
                    category=Category.STATEMENT,
                    severity=Severity.HIGH,
                    action=Action.DENY,
                    message="Row-locking clauses (FOR UPDATE/SHARE) are not permitted.",
                )
