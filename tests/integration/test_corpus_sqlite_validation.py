"""Independent validation of benchmark labels against a real SQLite engine.

* Every case expected to be ALLOWED must actually execute on the fixture database.
  This proves the "safe" queries are valid, legitimate SQL rather than strings the guard
  happens to accept.
"""

from __future__ import annotations

import sqlite3

import pytest

from sqlguard_ninja.benchmarking.dataset import load_dataset
from sqlguard_ninja.benchmarking.fixtures import create_sqlite
from tests.conftest import DATASET_PATH

DATASET = load_dataset(DATASET_PATH)
ALLOWED_SQLITE = [c for c in DATASET.cases if c.dialect == "sqlite" and c.expected.value == "allow"]


@pytest.fixture(scope="module")
def db():
    conn = create_sqlite(DATASET.policy)
    conn.execute("PRAGMA query_only = ON")
    yield conn
    conn.close()


def _bind(sql: str, context: dict) -> tuple[str, dict]:
    return sql, dict(context.items())


@pytest.mark.parametrize("case", ALLOWED_SQLITE, ids=lambda c: c.id)
def test_allowed_case_executes(db, case):
    sql, params = _bind(case.sql, case.context)
    try:
        db.execute(sql, params).fetchmany(5)
    except sqlite3.Error as exc:
        pytest.fail(f"{case.id} is labelled allow but SQLite rejects it: {exc}")
