"""Integration tests against a real PostgreSQL server (see tests/pg_support.py)."""

from __future__ import annotations

import re

import psycopg
import pytest

from sqlguard_ninja import Guard
from sqlguard_ninja.benchmarking.dataset import load_dataset
from sqlguard_ninja.integrations import RequestContext, SQLBlockedError, SQLCheckpoint
from sqlguard_ninja.integrations.executors import psycopg_executor
from sqlguard_ninja.query_cost.postgres import PlanInspectionRefused, PostgresPlanInspector
from tests.conftest import DATASET_PATH

pytestmark = pytest.mark.postgres

DATASET = load_dataset(DATASET_PATH)
ALLOWED_PG = [c for c in DATASET.cases if c.dialect == "postgres" and c.expected.value == "allow"]
PARAM = re.compile(r":tenant_id\b")


def _psycopg_sql(sql: str) -> tuple[str, dict | None]:
    """Test harness only: convert ':tenant_id' to psycopg's named style."""
    if PARAM.search(sql):
        return PARAM.sub("%(tenant_id)s", sql.replace("%", "%%")), {"tenant_id": 1}
    return sql, None


@pytest.mark.parametrize("case", ALLOWED_PG, ids=lambda c: c.id)
def test_allowed_case_executes_as_reader(pg, case):
    """Independent label validation: every 'allow' case runs on real PostgreSQL as the
    least-privilege reader inside a read-only transaction."""
    sql, params = _psycopg_sql(case.sql)
    with psycopg.connect(pg.reader_dsn) as conn, conn.transaction(force_rollback=True):
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        conn.execute(sql, params).fetchmany(5)


def test_reader_role_cannot_write(pg):
    """Database permissions are the final boundary, independent of the guard."""
    with (
        psycopg.connect(pg.reader_dsn) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM orders WHERE tenant_id = 1")


def test_checkpoint_with_psycopg_executor(pg, policy):
    cp = SQLCheckpoint(Guard(policy), dialect="postgres")
    ctx = RequestContext(principal="t", role="support_analyst", tenant_id=1)
    run = psycopg_executor(pg.reader_dsn)
    rows = cp.execute(
        "SELECT o.status, COUNT(*) AS n FROM orders o WHERE o.tenant_id = %(tenant_id)s "
        "GROUP BY o.status",
        ctx,
        run,
    )
    assert rows and {"status", "n"} <= set(rows[0])
    with pytest.raises(SQLBlockedError):
        cp.execute("SELECT o.id FROM orders o", ctx, run)


def test_audit_mode_write_still_fails_at_database(pg, policy):
    cp = SQLCheckpoint(Guard(policy), mode="audit", dialect="postgres")
    ctx = RequestContext(principal="t", role="support_analyst", tenant_id=1)
    with pytest.raises(psycopg.Error):
        cp.execute("DELETE FROM orders WHERE tenant_id = 1", ctx, psycopg_executor(pg.reader_dsn))


# --------------------------------------------------------------------------- plan inspector
def _inspector(pg, policy, **cost):
    p = policy.model_copy(update={"cost": policy.cost.model_copy(update=cost)})
    return PostgresPlanInspector(Guard(p), lambda: psycopg.connect(pg.reader_dsn))


def test_inspector_returns_plan_and_static_comparison(pg, policy):
    report = _inspector(pg, policy).inspect(
        "SELECT o.status, COUNT(*) FROM orders o WHERE o.tenant_id = %(tenant_id)s GROUP BY 1",
        role="support_analyst",
        context={"tenant_id": 1},
        params={"tenant_id": 1},
    )
    assert report.total_cost > 0
    assert any(n.relation == "orders" for n in report.nodes)
    d = report.as_dict()
    assert d["planner"]["total_cost"] == report.total_cost and d["static"] is not None
    assert report.decision.value == "allow"


def test_inspector_threshold_findings(pg, policy):
    inspector = _inspector(pg, policy, max_plan_total_cost=0.01, max_plan_rows=1)
    report = inspector.inspect(
        "SELECT o.id FROM orders o WHERE o.tenant_id = 1",
        role="support_analyst",
        context={"tenant_id": 1},
    )
    rules = {f.rule_id for f in report.findings}
    assert {"cost.planner_total_cost", "cost.planner_rows"} <= rules
    assert report.decision.value == "review"


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders WHERE tenant_id = 1",
        "SELECT o.id FROM orders o",  # tenant violation
        "SELECT p.card_number FROM payments p WHERE p.tenant_id = 1",
    ],
)
def test_inspector_refuses_non_allowed_sql(pg, policy, sql):
    with pytest.raises(PlanInspectionRefused):
        _inspector(pg, policy).inspect(sql, role="support_analyst", context={"tenant_id": 1})


def test_explain_does_not_execute(pg, policy):
    """EXPLAIN without ANALYZE must not run the query: a statement that would fail at
    execution time (division by zero on every row) plans successfully."""
    report = _inspector(pg, policy).inspect(
        "SELECT o.id, o.total_amount / (o.id - o.id) AS boom FROM orders o WHERE o.tenant_id = 1",
        role="support_analyst",
        context={"tenant_id": 1},
    )
    assert report.total_cost > 0
    with psycopg.connect(pg.reader_dsn) as conn, pytest.raises(psycopg.errors.DivisionByZero):
        conn.execute(
            "SELECT o.id, o.total_amount / (o.id - o.id) FROM orders o WHERE o.tenant_id = 1"
        ).fetchall()
