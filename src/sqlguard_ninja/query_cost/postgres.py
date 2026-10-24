"""Optional PostgreSQL execution-plan inspection.

Safety rules (see ADR-007):

* Only ``EXPLAIN (FORMAT JSON)`` is run — never ``EXPLAIN ANALYZE``, which executes the query.
* A statement is inspected only after :class:`~sqlguard_ninja.Guard` ALLOWed it. Planning can
  still evaluate immutable functions during constant folding, which is why the guard's
  function policy must run first.
* The EXPLAIN runs in a ``READ ONLY`` transaction with ``statement_timeout`` set locally,
  and the transaction is always rolled back.
* Connect with a low-privilege role. Never inspect untrusted SQL with privileged credentials.

Planner estimates are not guarantees of runtime or resource use.

Requires ``pip install "sqlguard-ninja[postgres]"``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlguard_ninja.core.analysis import analyse
from sqlguard_ninja.core.findings import Action, Category, Decision, Finding, Severity
from sqlguard_ninja.core.guard import Guard
from sqlguard_ninja.query_cost.static import StaticCostReport, analyse_static_cost


class PlanInspectionRefused(PermissionError):
    """The statement was not allowed by the guard, so it is not sent to the planner."""


@dataclass(frozen=True)
class PlanNodeSummary:
    node_type: str
    relation: str | None
    plan_rows: float
    total_cost: float


@dataclass
class PlanReport:
    total_cost: float
    plan_rows: float
    nodes: list[PlanNodeSummary]
    findings: list[Finding] = field(default_factory=list)
    static: StaticCostReport | None = None
    raw_plan: Any = None

    @property
    def decision(self) -> Decision:
        actions = {f.action for f in self.findings}
        if Action.DENY in actions:
            return Decision.DENY
        if Action.REVIEW in actions:
            return Decision.REVIEW
        return Decision.ALLOW

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "planner": {"total_cost": self.total_cost, "plan_rows": self.plan_rows},
            "static": self.static.as_dict() if self.static else None,
            "nodes": [n.__dict__ for n in self.nodes],
            "findings": [f.model_dump(mode="json") for f in self.findings],
        }


def _walk(plan: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield plan
    for child in plan.get("Plans", ()) or ():
        yield from _walk(child)


def summarise_plan(explain_json: Any) -> tuple[float, float, list[PlanNodeSummary]]:
    """Extract total cost, estimated rows and per-node summaries from EXPLAIN JSON output."""
    doc = explain_json[0] if isinstance(explain_json, list) else explain_json
    root = doc["Plan"]
    nodes = [
        PlanNodeSummary(
            node_type=str(n.get("Node Type")),
            relation=n.get("Relation Name"),
            plan_rows=float(n.get("Plan Rows", 0)),
            total_cost=float(n.get("Total Cost", 0)),
        )
        for n in _walk(root)
    ]
    return float(root.get("Total Cost", 0)), float(root.get("Plan Rows", 0)), nodes


def plan_findings(
    total_cost: float,
    plan_rows: float,
    nodes: list[PlanNodeSummary],
    *,
    max_total_cost: float | None,
    max_plan_rows: float | None,
    large_table_rows: int,
) -> list[Finding]:
    findings: list[Finding] = []
    if max_total_cost is not None and total_cost > max_total_cost:
        findings.append(
            Finding(
                rule_id="cost.planner_total_cost",
                category=Category.COST,
                severity=Severity.HIGH,
                action=Action.REVIEW,
                message=f"Planner cost estimate {total_cost:,.0f} exceeds the limit "
                f"{max_total_cost:,.0f}. Estimates are not guarantees.",
                metadata={"total_cost": total_cost},
            )
        )
    if max_plan_rows is not None and plan_rows > max_plan_rows:
        findings.append(
            Finding(
                rule_id="cost.planner_rows",
                category=Category.COST,
                severity=Severity.MEDIUM,
                action=Action.REVIEW,
                message=f"Planner expects {plan_rows:,.0f} result rows; the limit is "
                f"{max_plan_rows:,.0f}.",
                metadata={"plan_rows": plan_rows},
            )
        )
    for node in nodes:
        if node.node_type == "Seq Scan" and node.plan_rows >= large_table_rows:
            findings.append(
                Finding(
                    rule_id="cost.planner_seq_scan",
                    category=Category.COST,
                    severity=Severity.LOW,
                    action=Action.WARN,
                    message=f"Sequential scan of {node.relation} (~{node.plan_rows:,.0f} rows).",
                    table=node.relation,
                )
            )
        if node.node_type == "Nested Loop" and node.plan_rows >= large_table_rows:
            findings.append(
                Finding(
                    rule_id="cost.planner_nested_loop",
                    category=Category.COST,
                    severity=Severity.MEDIUM,
                    action=Action.WARN,
                    message=f"Nested loop producing ~{node.plan_rows:,.0f} rows.",
                )
            )
    return findings


ConnectionFactory = Callable[[], Any]


class PostgresPlanInspector:
    """Run guarded, non-executing ``EXPLAIN`` and compare planner and static estimates."""

    def __init__(
        self,
        guard: Guard,
        connect: ConnectionFactory,
        *,
        statement_timeout_ms: int = 2000,
    ) -> None:
        self.guard = guard
        self.connect = connect
        self.statement_timeout_ms = statement_timeout_ms

    @classmethod
    def from_conninfo(
        cls, guard: Guard, conninfo: str, **kwargs: Any
    ) -> PostgresPlanInspector:  # pragma: no cover - thin wrapper
        import psycopg  # noqa: PLC0415 - optional dependency

        return cls(guard, lambda: psycopg.connect(conninfo), **kwargs)

    def inspect(
        self,
        sql: str,
        *,
        role: str | None,
        context: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> PlanReport:
        """Validate, then EXPLAIN ``sql``. ``params`` are bound client-side by psycopg."""
        result = self.guard.validate(sql, role=role, dialect="postgres", context=context)
        if result.decision is not Decision.ALLOW:
            raise PlanInspectionRefused(
                f"guard decision is {result.decision.value}; only allowed statements are explained"
            )
        policy = self.guard.policy
        analysis = analyse(sql, "postgres", policy.catalog, max_nodes=policy.limits.max_ast_nodes)
        static = analyse_static_cost(analysis, policy)
        explain_json = self._explain(sql, params or {})
        total, rows, nodes = summarise_plan(explain_json)
        findings = plan_findings(
            total,
            rows,
            nodes,
            max_total_cost=policy.cost.max_plan_total_cost,
            max_plan_rows=policy.cost.max_plan_rows,
            large_table_rows=policy.cost.large_table_rows,
        )
        return PlanReport(total, rows, nodes, findings, static, explain_json)

    def _explain(self, sql: str, params: Mapping[str, Any]) -> Any:
        import psycopg  # noqa: PLC0415 - optional dependency

        conn = self.connect()
        try:
            with conn.transaction(force_rollback=True):
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.statement_timeout_ms),),
                )
                # Client-side binding: EXPLAIN cannot take server-side parameters.
                cur = psycopg.ClientCursor(conn)
                cur.execute("EXPLAIN (FORMAT JSON) " + sql, dict(params) or None)
                row = cur.fetchone()
        finally:
            conn.close()
        if row is None:  # pragma: no cover - EXPLAIN always returns one row
            raise RuntimeError("EXPLAIN returned no rows")
        value = row[0]
        return json.loads(value) if isinstance(value, str) else value
