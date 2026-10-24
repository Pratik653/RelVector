"""FastAPI service exposing guarded validation and execution.

Authentication here is a *demo stub* that maps an API-key header to a fixed principal.
Replace ``current_context`` with your real authentication. The request body can never set the
role or tenant.

Run:  uvicorn app:app --app-dir examples/fastapi   (needs: pip install ".[fastapi]" uvicorn)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import demo_database, load_policy
from fastapi import FastAPI, Header, HTTPException

from sqlguard_ninja import Guard
from sqlguard_ninja.integrations import (
    InMemoryAuditSink,
    RequestContext,
    SQLCheckpoint,
)
from sqlguard_ninja.integrations.executors import sqlite_executor
from sqlguard_ninja.integrations.fastapi import create_router

# Demo-only key table. Never hard-code credentials in a real service.
DEMO_KEYS = {
    "demo-support-t1": ("alice", "support_analyst", 1),
    "demo-hr": ("hank", "hr_analyst", None),
}

policy = load_policy()
audit = InMemoryAuditSink()
checkpoint = SQLCheckpoint(Guard(policy), dialect="sqlite", audit_sink=audit)
database = demo_database(policy)


def current_context(x_api_key: str = Header(...)) -> RequestContext:
    if x_api_key not in DEMO_KEYS:
        raise HTTPException(status_code=401, detail="unknown API key")
    principal, role, tenant = DEMO_KEYS[x_api_key]
    return RequestContext(principal=principal, role=role, tenant_id=tenant)


app = FastAPI(title="SQLGuard Ninja demo")
app.include_router(create_router(checkpoint, current_context, sqlite_executor(database)))
