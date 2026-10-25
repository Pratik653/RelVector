from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT, segment TEXT);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), status TEXT NOT NULL
);
CREATE TABLE shipments (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), delay_reason TEXT
);
"""


@pytest.fixture
def shop_db(tmp_path: Path) -> Path:
    path = tmp_path / "shop.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO customers VALUES (?,?,?)",
                         [(1, "a@example.com", "retail"), (2, "b@example.com", "wholesale")])
        conn.executemany("INSERT INTO orders VALUES (?,?,?)", [
            (1001, 1, "delivered"), (1002, 1, "delayed"), (1003, 2, "delayed"),
            (1004, None, "processing"), (1005, 2, "delayed"),
        ])
        conn.executemany("INSERT INTO shipments VALUES (?,?,?)", [
            (501, 1001, None),
            (502, 1002, "carrier capacity shortage"),
            (503, 1003, "truck breakdown"),
            (504, 1005, "port congestion"),
            (505, 1005, "customs hold"),
            (506, 1005, "missing paperwork"),
        ])
    conn.close()
    return path


@pytest.fixture(scope="session")
def admin_dsn(tmp_path_factory) -> str:
    """Admin DSN of a throwaway PostgreSQL server: RELVECTOR_PG_DSN, else embedded pgserver."""
    pytest.importorskip("psycopg")
    dsn = os.environ.get("RELVECTOR_PG_DSN")
    if dsn:
        return dsn
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata")), cleanup_mode="stop")
    return str(server.get_uri())


@pytest.fixture
def pg(admin_dsn) -> Iterator[tuple[str, str]]:
    """Yield (psycopg admin DSN of a fresh database, SQLAlchemy URL for RelVector)."""
    import psycopg
    from sqlalchemy.engine import make_url

    name = f"rv_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = make_url(admin_dsn).set(database=name)
    try:
        yield (url.render_as_string(hide_password=False),
               url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False))
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
