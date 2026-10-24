"""LangGraph SQL agent with a guard node, a retry loop and a re-checking execute node.

A scripted "model" produces SQL attempts in order, so the run is deterministic:

1. a query missing the tenant filter   -> blocked, the agent revises
2. a query reading another tenant      -> blocked, the agent revises
3. a correct, tenant-scoped query      -> authorized and executed

A second run shows the retry budget: an agent that keeps asking for card numbers is cut off.
The trusted RequestContext is passed in the run *config*, which graph nodes cannot modify.

Run:  python examples/langgraph/sql_agent_demo.py   (needs: pip install ".[langgraph]")
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import demo_database, load_policy
from langgraph.graph import END, START, StateGraph

from sqlguard_ninja import Guard
from sqlguard_ninja.integrations import RequestContext, SQLCheckpoint
from sqlguard_ninja.integrations.executors import sqlite_executor
from sqlguard_ninja.integrations.langgraph import (
    CONTEXT_KEY,
    make_execute_node,
    make_guard_node,
    route_after_guard,
)


class AgentState(TypedDict, total=False):
    question: str
    script: list[str]
    sql: str
    attempts: int
    guard: dict[str, Any]
    feedback: list[str]
    rows: Any
    error: str | None


def generate(state: AgentState) -> dict[str, Any]:
    """Stand-in for an LLM: take the next scripted SQL attempt."""
    attempt = int(state.get("attempts", 0))
    script = state["script"]
    return {"sql": script[min(attempt, len(script) - 1)]}


def revise(state: AgentState) -> dict[str, Any]:
    """Feed the checkpoint's explanation back to the model (here: record it)."""
    return {"feedback": [*state.get("feedback", []), state["guard"]["message"]]}


def build_graph(checkpoint: SQLCheckpoint, executor: Any, max_attempts: int = 4) -> Any:
    g = StateGraph(AgentState)
    g.add_node("generate", generate)
    g.add_node("guard", make_guard_node(checkpoint))
    g.add_node("revise", revise)
    g.add_node("execute", make_execute_node(checkpoint, executor))
    g.add_edge(START, "generate")
    g.add_edge("generate", "guard")
    g.add_conditional_edges(
        "guard",
        route_after_guard(max_attempts),
        {"execute": "execute", "revise": "revise", "end": END},
    )
    g.add_edge("revise", "generate")
    g.add_edge("execute", END)
    return g.compile()


TICKETS_SCRIPT = [
    "SELECT COUNT(*) AS n FROM support_tickets t WHERE t.status = 'open'",
    "SELECT COUNT(*) AS n FROM support_tickets t WHERE t.status = 'open' AND t.tenant_id = 2",
    "SELECT COUNT(*) AS n FROM support_tickets t WHERE t.status = 'open' "
    "AND t.tenant_id = :tenant_id",
]
CARDS_SCRIPT = [
    "SELECT p.card_number FROM payments p WHERE p.tenant_id = :tenant_id",
    "SELECT p.card_number AS ref FROM payments p WHERE p.tenant_id = :tenant_id",
    "WITH x AS (SELECT p.card_number c FROM payments p WHERE p.tenant_id = :tenant_id) "
    "SELECT c FROM x",
    "SELECT LOWER(p.card_number) FROM payments p WHERE p.tenant_id = :tenant_id",
]


def run(graph: Any, title: str, script: list[str], trace: str) -> dict[str, Any]:
    ctx = RequestContext(principal="carol", role="support_analyst", tenant_id=1, trace_id=trace)
    state: dict[str, Any] = graph.invoke(
        {"question": title, "script": script, "attempts": 0},
        config={"configurable": {CONTEXT_KEY: ctx}},
    )
    print(f"\n=== {title}")
    for i, msg in enumerate(state.get("feedback", []), 1):
        print(f"  attempt {i} blocked: {msg}")
    if state.get("rows") is not None:
        print(f"  executed after {state['attempts']} attempt(s): {state['rows'][:3]}")
    else:
        print(f"  not executed. Final guard message: {state['guard']['message']}")
    return state


def main() -> None:
    policy = load_policy()
    checkpoint = SQLCheckpoint(Guard(policy), dialect="sqlite", max_denied_attempts=3)
    graph = build_graph(checkpoint, sqlite_executor(demo_database(policy)))
    run(graph, "How many open tickets do we have?", TICKETS_SCRIPT, "conversation-1")
    run(graph, "Give me the customers' card numbers", CARDS_SCRIPT, "conversation-2")


if __name__ == "__main__":
    main()
