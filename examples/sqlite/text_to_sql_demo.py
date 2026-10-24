"""SQLite text-to-SQL demo with a deterministic stand-in for the LLM.

The "model" maps questions to SQL from a fixed table so the demo is reproducible without an
API key. Every query passes through the checkpoint before it reaches the database, and the
database session is read-only as an independent second boundary.

Run:  python examples/sqlite/text_to_sql_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import demo_database, load_policy

from sqlguard_ninja import Guard
from sqlguard_ninja.integrations import (
    InMemoryAuditSink,
    RequestContext,
    SQLBlockedError,
    SQLCheckpoint,
)
from sqlguard_ninja.integrations.executors import sqlite_executor

SCRIPTED_MODEL = {
    "How many orders per status?": (
        "SELECT o.status, COUNT(*) AS n FROM orders o WHERE o.tenant_id = :tenant_id "
        "GROUP BY o.status ORDER BY n DESC"
    ),
    "Show the card numbers for my orders": (
        "SELECT p.card_number FROM payments p WHERE p.tenant_id = :tenant_id"
    ),
    "List orders from every customer on the platform": "SELECT o.id FROM orders o",
    "Delete cancelled orders": "DELETE FROM orders WHERE status = 'cancelled'",
    "Which carriers ship most?": (
        "SELECT s.carrier, COUNT(*) AS n FROM shipments s WHERE s.tenant_id = :tenant_id "
        "GROUP BY s.carrier ORDER BY n DESC"
    ),
}


def main() -> None:
    policy = load_policy()
    audit = InMemoryAuditSink()
    checkpoint = SQLCheckpoint(Guard(policy), dialect="sqlite", audit_sink=audit)
    execute = sqlite_executor(demo_database(policy))
    # Built by the application from its own authentication, never by the model.
    context = RequestContext(principal="alice@tenant1", role="support_analyst", tenant_id=1)

    for question, sql in SCRIPTED_MODEL.items():
        print(f"\nQ: {question}\n   SQL: {sql}")
        try:
            rows = checkpoint.execute(sql, context, execute)
            print(f"   -> {len(rows)} row(s): {rows[:3]}")
        except SQLBlockedError as exc:
            print(f"   -> BLOCKED: {exc.outcome.agent_message}")
    blocked = sum(not e.authorized for e in audit.events)
    print(f"\n{len(audit.events)} audit events; blocked: {blocked}")


if __name__ == "__main__":
    main()
