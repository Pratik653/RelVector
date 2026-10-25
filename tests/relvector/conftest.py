from __future__ import annotations

import sqlite3
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
