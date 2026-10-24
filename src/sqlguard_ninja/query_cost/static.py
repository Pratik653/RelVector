"""Static, explainable query-cost heuristics.

The score is a sum of documented factor weights, capped at 100. It is a *risk indicator* for
gating and review, not a prediction of runtime. Row estimates come from the policy catalog
(``estimated_rows``); without them, size-dependent factors are skipped and reported as such.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlglot import exp

from sqlguard_ninja.core.analysis import QueryAnalysis, ScopeFacts
from sqlguard_ninja.core.findings import Action, Category, Finding, Severity
from sqlguard_ninja.core.rules.base import RuleContext
from sqlguard_ninja.policy.model import Policy

HUGE_LITERAL = 1_000_000

_GENERATOR_FUNCS = {"generate_series", "range", "sequence"}
_BLOWUP_FUNCS = {"repeat", "lpad", "rpad", "replicate", "space"}
_REGEX_TYPES: tuple[type[exp.Expr], ...] = tuple(
    getattr(exp, n) for n in ("RegexpLike", "RegexpILike", "RegexpExtract") if hasattr(exp, n)
)


@dataclass(frozen=True)
class CostFactor:
    code: str
    points: int
    explanation: str


@dataclass
class StaticCostReport:
    score: int
    factors: list[CostFactor] = field(default_factory=list)
    unknown_row_estimates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "factors": [f.__dict__ for f in self.factors],
            "unknown_row_estimates": self.unknown_row_estimates,
        }


def _int_literal(node: exp.Expr | None) -> int | None:
    while isinstance(node, (exp.Paren, exp.Cast)):
        node = node.this
    if isinstance(node, exp.Literal) and not node.is_string:
        try:
            return int(float(str(node.this)))
        except ValueError:
            return None
    return None


def _linked(select: exp.Select, left: str, right: str) -> bool:
    """True if WHERE contains an equality between columns of the two aliases."""
    where = select.args.get("where")
    if where is None:
        return False
    for eq in where.find_all(exp.EQ):
        tables = {c.table for c in eq.find_all(exp.Column)}
        if left in tables and right in tables:
            return True
    return False


def analyse_static_cost(analysis: QueryAnalysis, policy: Policy) -> StaticCostReport:
    factors: list[CostFactor] = []
    unknown: set[str] = set()
    large = policy.cost.large_table_rows
    catalog = policy.catalog

    def rows(name: str) -> int | None:
        t = catalog.tables.get(name)
        if t is None or t.estimated_rows is None:
            unknown.add(name)
            return None
        return t.estimated_rows

    root_has_limit = bool(analysis.scopes) and analysis.scopes[-1].has_limit
    for facts in analysis.scopes:
        factors.extend(_scope_factors(facts, rows, large, root_has_limit))

    if analysis.join_count > 3:
        factors.append(
            CostFactor(
                "many_joins",
                5 * (analysis.join_count - 3),
                f"{analysis.join_count} joins; each join beyond three adds planning and "
                "execution cost.",
            )
        )
    if analysis.max_depth > 2:
        factors.append(
            CostFactor(
                "deep_nesting",
                5 * (analysis.max_depth - 2),
                f"subqueries nested {analysis.max_depth} levels deep",
            )
        )
    root = analysis.qualified
    if root is not None:
        factors.extend(_expression_factors(root))
    score = min(100, sum(f.points for f in factors))
    return StaticCostReport(score=score, factors=factors, unknown_row_estimates=sorted(unknown))


def _scope_factors(
    facts: ScopeFacts, rows: object, large: int, root_has_limit: bool
) -> Iterator[CostFactor]:
    assert callable(rows)
    select = facts.expression
    if not isinstance(select, exp.Select):
        return
    base = [t for t in facts.tables if not t.is_function]
    sizes = {t.alias: rows(t.name) for t in base}
    big = [a for a, n in sizes.items() if n is not None and n >= large]
    has_where = select.args.get("where") is not None

    joins: list[exp.Join] = list(select.args.get("joins") or [])
    from_ = select.args.get("from_") or select.args.get("from")
    first_alias = from_.this.alias_or_name if from_ is not None and from_.this else None
    for join in joins:
        alias = join.alias_or_name
        kind = (join.kind or "").upper()
        no_condition = not join.args.get("on") and not join.args.get("using")
        if (kind == "CROSS" or no_condition) and not (
            first_alias and _linked(select, first_alias, alias)
        ):
            n_left = sizes.get(first_alias or "")
            n_right = sizes.get(alias)
            weight = 40 if (n_left or 0) >= large or (n_right or 0) >= large else 25
            yield CostFactor(
                "cartesian_join",
                weight,
                f"join with {alias} has no join condition (Cartesian product)",
            )
    if len(big) >= 2 and any(sizes[a] is not None for a in big):
        names = sorted({t.name for t in base if t.alias in big})
        if len(names) < len(big):
            yield CostFactor("large_self_join", 10, "a large table is joined with itself")

    for alias in big:
        if not has_where:
            yield CostFactor(
                "large_scan_no_filter",
                25,
                f"{alias} has an estimated {sizes[alias]:,} rows and is read without a filter",
            )
    if big and not root_has_limit and facts.depth == 0:
        yield CostFactor("no_limit_on_large", 10, "large result possible and no LIMIT")
    if big and select.args.get("order") and not facts.has_limit:
        yield CostFactor("sort_without_limit", 10, "sorting a large input without LIMIT")
    if big and select.args.get("distinct"):
        yield CostFactor("distinct_on_large", 5, "DISTINCT over a large input")
    if big and has_where:
        where = select.args["where"]
        for like in where.find_all(exp.Like, exp.ILike):
            pattern = like.expression
            if isinstance(pattern, exp.Literal) and str(pattern.this).startswith("%"):
                yield CostFactor(
                    "leading_wildcard", 10, "LIKE pattern starts with % and cannot use an index"
                )
                break
        if _REGEX_TYPES and any(True for _ in where.find_all(*_REGEX_TYPES)):
            yield CostFactor("regex_filter", 5, "regular-expression filter on a large table")
    if big and any(isinstance(p, exp.Subquery) or p.find(exp.Subquery) for p in select.expressions):
        yield CostFactor(
            "correlated_select_subquery",
            10,
            "subquery in the SELECT list may run once per row of a large table",
        )


def _expression_factors(root: exp.Expr) -> Iterator[CostFactor]:
    with_ = root.args.get("with_") or root.args.get("with")
    if isinstance(with_, exp.With) and with_.args.get("recursive"):
        yield CostFactor(
            "recursive_cte", 30, "recursive CTE; termination cannot be verified statically"
        )
        for cte in with_.expressions:
            body = cte.this
            if isinstance(body, exp.Union):
                recursive_arm = body.expression
                if (
                    isinstance(recursive_arm, exp.Select)
                    and recursive_arm.args.get("where") is None
                ):
                    yield CostFactor(
                        "unbounded_recursion",
                        30,
                        f"recursive arm of {cte.alias_or_name} has no terminating condition",
                    )
    for func in root.find_all(exp.Func):
        name = func.name.lower() if isinstance(func, exp.Anonymous) else func.sql_name().lower()
        if isinstance(func, getattr(exp, "GenerateSeries", ())):
            name = "generate_series"
        if name in _GENERATOR_FUNCS:
            values = [_int_literal(a) for a in func.args.values() if isinstance(a, exp.Expr)]
            numbers = [v for v in values if v is not None]
            if numbers and max(map(abs, numbers)) >= HUGE_LITERAL:
                yield CostFactor("row_generator", 60, f"{name}() generating a very large range")
            elif not numbers or len(numbers) < len(values):
                yield CostFactor("row_generator", 40, f"{name}() with a non-literal bound")
        elif name in _BLOWUP_FUNCS:
            values = [_int_literal(a) for a in func.args.values() if isinstance(a, exp.Expr)]
            if any(v is not None and v >= HUGE_LITERAL for v in values):
                yield CostFactor("string_blowup", 60, f"{name}() with a very large size argument")


class StaticCostRule:
    """Turn the static cost score into findings using the policy thresholds."""

    rule_ids = ("cost.static_score",)

    def check(self, ctx: RuleContext) -> Iterator[Finding]:
        cfg = ctx.policy.cost
        if not cfg.enabled:
            return
        report = analyse_static_cost(ctx.analysis, ctx.policy)
        if report.score < cfg.review_score:
            return
        action = Action.DENY if report.score >= cfg.deny_score else Action.REVIEW
        top = sorted(report.factors, key=lambda f: -f.points)[:3]
        yield Finding(
            rule_id="cost.static_score",
            category=Category.COST,
            severity=Severity.HIGH if action is Action.DENY else Severity.MEDIUM,
            action=action,
            message=f"Estimated query cost risk is {report.score}/100: "
            + "; ".join(f.explanation for f in top)
            + ".",
            metadata=report.as_dict(),
            remediation="Add selective filters, join conditions and a LIMIT.",
        )
