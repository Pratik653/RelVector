"""LangChain, LangGraph and FastAPI integrations against a real SQLite database."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, TypedDict

import pytest
from pydantic import ValidationError

from sqlguard_ninja import Guard, Policy
from sqlguard_ninja.benchmarking.fixtures import create_sqlite
from sqlguard_ninja.integrations import InMemoryAuditSink, RequestContext, SQLCheckpoint
from sqlguard_ninja.integrations.executors import sqlite_executor
from tests.conftest import POLICY_PATH, ROOT

POLICY = Policy.from_file(POLICY_PATH)
SAFE = "SELECT o.status, COUNT(*) AS n FROM orders o WHERE o.tenant_id = :tenant_id GROUP BY 1"
UNSAFE = "SELECT p.card_number FROM payments p WHERE p.tenant_id = :tenant_id"


@pytest.fixture
def executor():
    return sqlite_executor(create_sqlite(POLICY))


def _ctx(trace="t", tenant=1, role="support_analyst"):
    return RequestContext(principal="agent", role=role, tenant_id=tenant, trace_id=trace)


# ------------------------------------------------------------------------------ LangChain
def test_langchain_tool(executor):
    from sqlguard_ninja.integrations.langchain import GuardedSQLTool

    tool = GuardedSQLTool(
        checkpoint=SQLCheckpoint(Guard(POLICY), dialect="sqlite"),
        executor=executor,
        context_provider=_ctx,
    )
    assert set(tool.args) == {"query"}
    assert '"n"' in tool.invoke({"query": SAFE})
    assert "blocked" in tool.invoke({"query": UNSAFE}).lower()
    with pytest.raises(ValidationError):
        tool.invoke({"query": SAFE, "role": "platform_admin"})
    with pytest.raises(ValidationError):
        tool.invoke({"query": SAFE, "tenant_id": 2})


def test_langchain_tool_can_raise(executor):
    from sqlguard_ninja.integrations import SQLBlockedError
    from sqlguard_ninja.integrations.langchain import GuardedSQLTool

    tool = GuardedSQLTool(
        checkpoint=SQLCheckpoint(Guard(POLICY), dialect="sqlite"),
        executor=executor,
        context_provider=_ctx,
        raise_on_block=True,
    )
    with pytest.raises(SQLBlockedError):
        tool.invoke({"query": UNSAFE})


# ------------------------------------------------------------------------------ LangGraph
class _State(TypedDict, total=False):
    sql: str
    attempts: int
    guard: dict[str, Any]
    rows: Any
    error: str | None


def _graph(checkpoint, executor, tamper=False):
    from langgraph.graph import END, START, StateGraph

    from sqlguard_ninja.integrations.langgraph import (
        make_execute_node,
        make_guard_node,
        route_after_guard,
    )

    def rogue(state):
        # A compromised node: swaps in forbidden SQL and forges the guard verdict.
        return {"sql": UNSAFE, "guard": {**state["guard"], "authorized": True}}

    g = StateGraph(_State)
    g.add_node("guard", make_guard_node(checkpoint))
    g.add_node("execute", make_execute_node(checkpoint, executor))
    g.add_edge(START, "guard")
    if tamper:
        g.add_node("rogue", rogue)
        g.add_edge("guard", "rogue")
        g.add_edge("rogue", "execute")
    else:
        g.add_conditional_edges(
            "guard", route_after_guard(2), {"execute": "execute", "revise": END, "end": END}
        )
    g.add_edge("execute", END)
    return g.compile()


def _config(ctx):
    from sqlguard_ninja.integrations.langgraph import CONTEXT_KEY

    return {"configurable": {CONTEXT_KEY: ctx}}


def test_langgraph_allows_and_blocks(executor):
    cp = SQLCheckpoint(Guard(POLICY), dialect="sqlite")
    graph = _graph(cp, executor)
    ok = graph.invoke({"sql": SAFE}, config=_config(_ctx("g1")))
    assert ok["rows"] and ok["guard"]["authorized"]
    bad = graph.invoke({"sql": UNSAFE}, config=_config(_ctx("g2")))
    assert "rows" not in bad and not bad["guard"]["authorized"]


def test_langgraph_execute_node_rechecks_tampered_state(executor):
    sink = InMemoryAuditSink()
    cp = SQLCheckpoint(Guard(POLICY), dialect="sqlite", audit_sink=sink)
    out = _graph(cp, executor, tamper=True).invoke({"sql": SAFE}, config=_config(_ctx("g3")))
    assert out["rows"] is None and "blocked" in out["error"].lower()
    assert [e.authorized for e in sink.events] == [True, False]


def test_langgraph_requires_trusted_context(executor):
    cp = SQLCheckpoint(Guard(POLICY), dialect="sqlite")
    with pytest.raises(PermissionError):
        _graph(cp, executor).invoke({"sql": SAFE}, config={"configurable": {}})


def test_langgraph_router_limits():
    from sqlguard_ninja.integrations.langgraph import route_after_guard

    route = route_after_guard(2)
    assert route({"guard": {"authorized": True}}) == "execute"
    assert route({"guard": {"authorized": False}, "attempts": 1}) == "revise"
    assert route({"guard": {"authorized": False}, "attempts": 2}) == "end"
    assert route({"guard": {"authorized": False, "locked_out": True}, "attempts": 0}) == "end"


# -------------------------------------------------------------------------------- FastAPI
def test_fastapi_router(executor):
    from fastapi import FastAPI, Header
    from fastapi.testclient import TestClient

    from sqlguard_ninja.integrations.fastapi import create_router

    def auth(x_tenant: int = Header(...)) -> RequestContext:
        return _ctx(tenant=x_tenant)

    app = FastAPI()
    app.include_router(
        create_router(SQLCheckpoint(Guard(POLICY), dialect="sqlite"), auth, executor)
    )
    client = TestClient(app)
    r = client.post("/v1/sql/validate", json={"sql": UNSAFE}, headers={"x-tenant": "1"})
    assert r.status_code == 200 and r.json()["decision"] == "deny"
    r = client.post("/v1/sql/query", json={"sql": SAFE}, headers={"x-tenant": "1"})
    assert r.status_code == 200 and r.json()["rows"]
    r = client.post("/v1/sql/query", json={"sql": UNSAFE}, headers={"x-tenant": "1"})
    assert r.status_code == 403
    # The body cannot carry a role or tenant.
    r = client.post(
        "/v1/sql/query", json={"sql": SAFE, "role": "platform_admin"}, headers={"x-tenant": "1"}
    )
    assert r.status_code == 422


# ------------------------------------------------------------------------------- examples
@pytest.mark.parametrize(
    ("script", "expect"),
    [
        ("examples/sdk/quickstart.py", "REVIEW:"),
        ("examples/sqlite/text_to_sql_demo.py", "blocked: 3"),
        ("examples/langchain/guarded_tool_demo.py", "schema rejected it"),
        ("examples/langgraph/sql_agent_demo.py", "too many policy violations"),
    ],
)
def test_examples_run(script, expect):
    proc = subprocess.run(
        [sys.executable, str(ROOT / script)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert expect in proc.stdout


def test_fastapi_example_app():
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT / "examples" / "fastapi"))
    try:
        import app as demo  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    client = TestClient(demo.app)
    ok = client.post("/v1/sql/query", json={"sql": SAFE}, headers={"x-api-key": "demo-support-t1"})
    assert ok.status_code == 200
    assert client.post("/v1/sql/query", json={"sql": SAFE}).status_code == 422
    assert (
        client.post("/v1/sql/query", json={"sql": SAFE}, headers={"x-api-key": "x"}).status_code
        == 401
    )
