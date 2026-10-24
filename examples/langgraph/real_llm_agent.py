"""OPTIONAL: the same guarded tool driven by a real chat model. Not run by the test-suite.

Requires ``pip install langchain langgraph`` plus your model provider's LangChain package and
API key. Choose the model with ``SQLNINJA_DEMO_MODEL`` (any ``init_chat_model`` string).
This example has **not** been executed against a live model in this repository's tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import demo_database, load_policy

from sqlguard_ninja import Guard
from sqlguard_ninja.integrations import RequestContext, SQLCheckpoint
from sqlguard_ninja.integrations.executors import sqlite_executor
from sqlguard_ninja.integrations.langchain import GuardedSQLTool


def main() -> None:
    model_name = os.environ.get("SQLNINJA_DEMO_MODEL")
    if not model_name:
        sys.exit("Set SQLNINJA_DEMO_MODEL (and the provider's API key) to run this demo.")
    from langchain.chat_models import init_chat_model  # type: ignore[import-not-found]
    from langgraph.prebuilt import create_react_agent

    policy = load_policy()
    tool = GuardedSQLTool(
        checkpoint=SQLCheckpoint(Guard(policy), dialect="sqlite"),
        executor=sqlite_executor(demo_database(policy)),
        context_provider=lambda: RequestContext(
            principal="demo", role="support_analyst", tenant_id=1
        ),
    )
    agent = create_react_agent(init_chat_model(model_name), [tool])
    question = sys.argv[1] if len(sys.argv) > 1 else "How many orders per status do we have?"
    result = agent.invoke({"messages": [("user", question)]})
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
