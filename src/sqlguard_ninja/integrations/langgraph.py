"""LangGraph integration: guard and execute nodes plus a router.

Trust model:

* The request context is read from ``config["configurable"][CONTEXT_KEY]``, which the
  *application* sets when it invokes the graph. Graph nodes (including LLM nodes) can write
  state, but they cannot change the run configuration.
* :func:`make_execute_node` re-evaluates the SQL through the checkpoint. It never trusts an
  ``authorized`` flag found in state, so a node that tampers with state gains nothing.

Install with ``pip install "sqlguard-ninja[langgraph]"``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.runnables import RunnableConfig

from sqlguard_ninja.integrations.checkpoint import RequestContext, SQLBlockedError, SQLCheckpoint

CONTEXT_KEY = "sqlninja_context"

State = Mapping[str, Any]
Node = Callable[[State, RunnableConfig], dict[str, Any]]


def _context(config: Any) -> RequestContext:
    configurable = (config or {}).get("configurable", {}) if isinstance(config, Mapping) else {}
    ctx = configurable.get(CONTEXT_KEY)
    if not isinstance(ctx, RequestContext):
        raise PermissionError(
            f"missing trusted RequestContext in config['configurable'][{CONTEXT_KEY!r}]"
        )
    return ctx


def make_guard_node(checkpoint: SQLCheckpoint, sql_key: str = "sql") -> Node:
    """Node that evaluates ``state[sql_key]`` and records the verdict under ``guard``."""

    # LangGraph injects the run config only when the parameter is annotated RunnableConfig.
    def guard_node(state: State, config: RunnableConfig) -> dict[str, Any]:
        outcome = checkpoint.evaluate(str(state.get(sql_key, "")), _context(config))
        return {
            "guard": {
                "authorized": outcome.authorized,
                "decision": outcome.result.decision.value,
                "message": outcome.agent_message,
                "rules": [f.rule_id for f in outcome.result.blocking_findings],
                "locked_out": outcome.locked_out,
            },
            "attempts": int(state.get("attempts", 0)) + 1,
        }

    return guard_node


def make_execute_node(
    checkpoint: SQLCheckpoint,
    executor: Callable[[str, Mapping[str, Any]], Any],
    sql_key: str = "sql",
) -> Node:
    """Node that executes the SQL *after re-checking it*; writes ``rows`` or ``error``."""

    def execute_node(state: State, config: RunnableConfig) -> dict[str, Any]:
        try:
            rows = checkpoint.execute(str(state.get(sql_key, "")), _context(config), executor)
        except SQLBlockedError as exc:
            return {"rows": None, "error": exc.outcome.agent_message}
        return {"rows": rows, "error": None}

    return execute_node


def route_after_guard(max_attempts: int = 3) -> Callable[[State], str]:
    """Router: ``"execute"`` if authorized, ``"revise"`` to retry, ``"end"`` when exhausted."""

    def route(state: State) -> str:
        guard = state.get("guard") or {}
        if guard.get("authorized"):
            return "execute"
        if guard.get("locked_out") or int(state.get("attempts", 0)) >= max_attempts:
            return "end"
        return "revise"

    return route
