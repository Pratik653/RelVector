"""LangChain: a SQL tool whose execution is gated by the checkpoint.

The tool is invoked exactly as an agent would invoke it (``tool.invoke({...})``). Its
argument schema has only ``query``; the model cannot pass a role, tenant or approval.

Run:  python examples/langchain/guarded_tool_demo.py   (needs: pip install ".[langchain]")
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import demo_database, load_policy
from pydantic import ValidationError

from sqlguard_ninja import Guard
from sqlguard_ninja.integrations import RequestContext, SQLCheckpoint
from sqlguard_ninja.integrations.executors import sqlite_executor
from sqlguard_ninja.integrations.langchain import GuardedSQLTool


def main() -> None:
    policy = load_policy()
    tool = GuardedSQLTool(
        checkpoint=SQLCheckpoint(Guard(policy), dialect="sqlite"),
        executor=sqlite_executor(demo_database(policy)),
        context_provider=lambda: RequestContext(
            principal="bob@tenant2", role="support_analyst", tenant_id=2
        ),
    )
    print("Tool schema seen by the model:", tool.args)
    for query in [
        "SELECT t.priority, COUNT(*) AS n FROM support_tickets t "
        "WHERE t.tenant_id = :tenant_id GROUP BY t.priority",
        "SELECT t.id FROM support_tickets t WHERE t.tenant_id = 1",  # another tenant
        "SELECT e.salary FROM employees e",
    ]:
        print(f"\n> {query}\n{tool.invoke({'query': query})}")

    try:
        tool.invoke({"query": "SELECT 1", "role": "platform_admin"})
    except ValidationError:
        print("\nThe model tried to pass a role; the tool schema rejected it.")


if __name__ == "__main__":
    main()
