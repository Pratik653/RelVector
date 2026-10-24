"""LangChain integration: a SQL tool whose execution is gated by :class:`SQLCheckpoint`.

The tool's argument schema contains **only** the query. Role, tenant and approvals cannot be
supplied by the model; they come from ``context_provider``, which the application binds to its
authenticated request. Install with ``pip install "sqlguard-ninja[langchain]"``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from sqlguard_ninja.integrations.checkpoint import RequestContext, SQLBlockedError, SQLCheckpoint

Executor = Callable[[str, Mapping[str, Any]], Any]


class SQLQueryInput(BaseModel):
    """Arguments the model may send. Extra fields (e.g. ``role``) are rejected."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="A single read-only SQL SELECT statement.")


class GuardedSQLTool(BaseTool):
    """Run SQL only after the checkpoint authorizes it; return rows or the policy reason."""

    name: str = "sql_db_query"
    description: str = (
        "Run a read-only SQL query against the database and return rows as JSON. "
        "Queries are checked against a server-side data access policy before execution; "
        "if a query is blocked, the response explains why. Use bind parameter :tenant_id "
        "for the current tenant."
    )
    args_schema: type[BaseModel] = SQLQueryInput
    raise_on_block: bool = False

    _checkpoint: SQLCheckpoint = PrivateAttr()
    _executor: Executor = PrivateAttr()
    _context_provider: Callable[[], RequestContext] = PrivateAttr()

    def __init__(
        self,
        checkpoint: SQLCheckpoint,
        executor: Executor,
        context_provider: Callable[[], RequestContext],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._checkpoint = checkpoint
        self._executor = executor
        self._context_provider = context_provider

    def _run(self, query: str, **_: Any) -> str:
        context = self._context_provider()
        try:
            rows = self._checkpoint.execute(query, context, self._executor)
        except SQLBlockedError as exc:
            if self.raise_on_block:
                raise
            return exc.outcome.agent_message
        return json.dumps(rows, default=str)
