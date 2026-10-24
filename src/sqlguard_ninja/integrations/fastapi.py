"""FastAPI integration: a router exposing validation and guarded execution.

Authentication is the application's job. Pass a dependency that returns a
:class:`RequestContext` built from your own auth (session, JWT, mTLS...). The request body
can never set the role or tenant. Install with ``pip install "sqlguard-ninja[fastapi]"``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sqlguard_ninja.integrations.checkpoint import RequestContext, SQLBlockedError, SQLCheckpoint


class SQLRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(max_length=100_000)


class FindingOut(BaseModel):
    rule_id: str
    action: str
    message: str
    remediation: str | None = None


class ValidateResponse(BaseModel):
    decision: str
    authorized: bool
    message: str
    findings: list[FindingOut]
    trace_id: str


def create_router(
    checkpoint: SQLCheckpoint,
    context_dependency: Callable[..., RequestContext],
    executor: Callable[[str, Mapping[str, Any]], Any] | None = None,
    prefix: str = "/v1/sql",
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["sql"])

    @router.post("/validate", response_model=ValidateResponse)
    def validate(
        body: SQLRequest,
        ctx: RequestContext = Depends(context_dependency),  # noqa: B008
    ) -> ValidateResponse:
        outcome = checkpoint.evaluate(body.sql, ctx)
        return ValidateResponse(
            decision=outcome.result.decision.value,
            authorized=outcome.authorized,
            message=outcome.agent_message,
            findings=[
                FindingOut(
                    rule_id=f.rule_id,
                    action=f.action.value,
                    message=f.message,
                    remediation=f.remediation,
                )
                for f in outcome.result.findings
            ],
            trace_id=ctx.trace_id,
        )

    if executor is not None:
        run = executor

        @router.post("/query")
        def query(
            body: SQLRequest,
            ctx: RequestContext = Depends(context_dependency),  # noqa: B008
        ) -> dict[str, Any]:
            try:
                rows = checkpoint.execute(body.sql, ctx, run)
            except SQLBlockedError as exc:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "decision": exc.outcome.result.decision.value,
                        "message": exc.outcome.agent_message,
                    },
                ) from exc
            return {"rows": rows, "trace_id": ctx.trace_id}

    return router
