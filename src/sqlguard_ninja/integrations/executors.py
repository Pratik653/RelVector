"""Small, safe executors used by the integrations and examples.

These are the *last* line of defence after the checkpoint: they open read-only sessions so
that the database itself refuses writes even if a query were authorized by mistake (or
deliberately, in audit mode). Use a least-privilege database account in production.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Mapping
from typing import Any

Rows = list[dict[str, Any]]


def _bound_params(sql: str, params: Mapping[str, Any]) -> dict[str, Any]:
    # Only pass parameters the statement mentions; sqlite3 ignores extras for named style,
    # but filtering keeps driver errors clear.
    return {k: v for k, v in params.items() if f":{k}" in sql or f"%({k})s" in sql}


def sqlite_executor(conn: sqlite3.Connection, max_rows: int = 200) -> Callable[..., Rows]:
    """Execute on SQLite with ``PRAGMA query_only = ON`` (writes fail at the engine).

    Calls are serialised with a lock so one connection can be shared by threaded servers;
    open it with ``check_same_thread=False`` for that.
    """
    conn.execute("PRAGMA query_only = ON")
    lock = threading.Lock()

    def run(sql: str, params: Mapping[str, Any]) -> Rows:
        with lock:
            cur = conn.execute(sql, _bound_params(sql, params))
            cols = [d[0] for d in cur.description or ()]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchmany(max_rows)]

    return run


def psycopg_executor(
    conninfo: str, max_rows: int = 200, statement_timeout_ms: int = 5000
) -> Callable[..., Rows]:  # pragma: no cover - exercised by PostgreSQL integration tests
    """Execute on PostgreSQL in a READ ONLY transaction with a statement timeout.

    Use ``%(tenant_id)s`` style bind parameters in SQL sent to PostgreSQL.
    """
    import psycopg  # noqa: PLC0415 - optional dependency
    from psycopg.rows import dict_row  # noqa: PLC0415

    def run(sql: str, params: Mapping[str, Any]) -> Rows:
        with (
            psycopg.connect(conninfo, row_factory=dict_row) as conn,
            conn.transaction(force_rollback=True),
        ):
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute(
                "SELECT set_config('statement_timeout', %s, true)", (str(statement_timeout_ms),)
            )
            cur = conn.execute(sql, _bound_params(sql, params))
            return list(cur.fetchmany(max_rows))

    return run
