"""PostgreSQL plan inspection: static cost score vs. planner estimate, without executing.

Needs a PostgreSQL server with the fixture data loaded. Either:

* ``docker compose -f docker/docker-compose.yml up -d`` and
  ``SQLNINJA_PG_DSN=postgresql://postgres:sqlninja-dev@localhost:55432/postgres``, or
* ``pip install pgserver`` (embedded server, no Docker needed).

Run:  python examples/postgresql/plan_inspection_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

import psycopg  # noqa: E402
from _shared import load_policy  # noqa: E402

from sqlguard_ninja import Guard  # noqa: E402
from sqlguard_ninja.query_cost.postgres import PlanInspectionRefused, PostgresPlanInspector  # noqa: E402
from tests.pg_support import setup_pg  # noqa: E402

QUERIES = [
    ("support_analyst", "SELECT o.status, COUNT(*) FROM orders o WHERE o.tenant_id = 1 GROUP BY 1"),
    ("platform_admin", "SELECT o.id FROM orders o JOIN order_items i ON i.order_id = o.id"),
    ("platform_admin", "SELECT o.id, i.id FROM orders o CROSS JOIN order_items i"),
]


def main() -> None:
    policy = load_policy()
    env = setup_pg(policy)
    if env is None:
        sys.exit("No PostgreSQL available: set SQLNINJA_PG_DSN or `pip install pgserver`.")
    inspector = PostgresPlanInspector(Guard(policy), lambda: psycopg.connect(env.reader_dsn))
    for role, sql in QUERIES:
        print(f"\n[{role}] {sql}")
        try:
            report = inspector.inspect(sql, role=role, context={"tenant_id": 1})
        except PlanInspectionRefused as exc:
            print(f"  refused before reaching the planner: {exc}")
            continue
        static = report.static.score if report.static else None
        print(f"  static risk score: {static}/100")
        print(f"  planner: total cost {report.total_cost:,.1f}, rows {report.plan_rows:,.0f}")
        for f in report.findings:
            print(f"  [{f.action.value}] {f.message}")


if __name__ == "__main__":
    main()
