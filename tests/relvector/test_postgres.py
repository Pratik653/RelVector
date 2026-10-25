"""PostgreSQL validation on a disposable database.

Uses ``RELVECTOR_PG_DSN`` (an admin DSN for a throwaway server, e.g. a CI service container) or,
if unset, an embedded server from the optional ``pgserver`` package. Skips otherwise. Each test
creates and drops its own database; nothing outside it is touched.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from relvector import HashingEmbedding, RelVector, RunSupersededError

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.postgres


SHOP = """
CREATE TABLE customers (id integer PRIMARY KEY, segment text, email text);
CREATE TABLE orders (id integer PRIMARY KEY, customer_id integer REFERENCES customers(id),
                     status text NOT NULL);
CREATE TABLE shipments (id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES orders(id),
                        delay_reason text);
INSERT INTO customers VALUES (1, 'retail', 'a@example.com'), (2, 'wholesale', 'b@example.com');
INSERT INTO orders VALUES (1001, 1, 'delivered'), (1002, 1, 'delayed'), (1003, 2, 'delayed'),
                          (1004, NULL, 'processing'), (1005, 2, 'delayed');
INSERT INTO shipments VALUES (501, 1001, NULL), (502, 1002, 'carrier capacity shortage'),
    (503, 1003, 'truck breakdown'), (504, 1005, 'port congestion'), (505, 1005, 'customs hold');
"""


def rv_for(url: str, tmp_path, name: str = "i.rv", **kw) -> RelVector:
    kw.setdefault("embedding_provider", HashingEmbedding(256))
    return RelVector(url, index_path=tmp_path / name, **kw)


def test_pg_read_only_schema_extraction_index_and_provenance(pg, tmp_path):
    admin, url = pg
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(SHOP)
    seen: list[str] = []
    with rv_for(url, tmp_path, sql_validator=seen.append) as rv:
        assert "password" not in repr(rv).lower()
        with rv.engine.connect() as conn:
            from sqlalchemy import text
            assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
            assert conn.execute(text("SHOW transaction_isolation")).scalar() == "repeatable read"
            with pytest.raises(Exception, match="read-only transaction"):
                conn.execute(text("UPDATE orders SET status = 'x'"))

        schema = rv.inspect_schema()
        assert {str(fk) for fk in schema.foreign_keys} == {
            "orders(customer_id) -> customers(id)", "shipments(order_id) -> orders(id)"}
        rv.configure(root_table="orders", include_tables=["shipments", "customers"],
                     text_fields=["orders.status", "shipments.delay_reason", "customers.segment"],
                     metadata_fields=["orders.status"], exclude_fields=["customers.email"],
                     max_children=1)
        stats = rv.index(batch_size=2)
        assert (stats.rows, stats.batches, stats.embedded) == (5, 3, 5)
        roots = [s for s in seen if "FROM orders" in s]
        assert "orders.id >" not in roots[0] and all("orders.id > :id_1" in s for s in roots[1:])
        assert all("OFFSET" not in s.upper() for s in roots)  # PostgreSQL renders no OFFSET
        assert not any("email" in s for s in seen)

        hit = rv.search("carrier capacity shortage", top_k=1)[0]
        assert (hit.source_table, hit.source_pk) == ("orders", {"id": 1002})
        assert {"table": "shipments", "relation": "one_to_many", "pk": {"id": 502}} \
            in hit.references
        trunc = next(h for h in rv.search("port", top_k=5) if h.source_pk == {"id": 1005})
        assert trunc.truncated == {"shipments": 1} and "2 in total" in trunc.text
        assert rv.index(batch_size=2).embedded == 0  # idempotent re-index


class FailOnce(HashingEmbedding):
    def __init__(self, fail_on_call: int) -> None:
        super().__init__(256)
        self.calls, self.fail_on_call = 0, fail_on_call

    def embed(self, texts):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("interrupted")
        return super().embed(texts)


@pytest.mark.parametrize("ddl,rows,key_type", [
    ("CREATE TABLE items (k date PRIMARY KEY, label text)",
     [(dt.date(2024, 1, d), f"day {d}") for d in (2, 9, 10, 11, 30)], dt.date),
    ("CREATE TABLE items (k uuid PRIMARY KEY, label text)",
     # Values chosen so text order and UUID order differ in the first byte.
     [(uuid.UUID(int=n << 120), f"item {n}") for n in (1, 9, 10, 160, 255)], uuid.UUID),
    ("CREATE TABLE items (k timestamptz PRIMARY KEY, label text)",
     [(dt.datetime(2024, 1, 1, h, tzinfo=dt.UTC), f"hour {h}") for h in (1, 2, 9, 10, 23)],
     dt.datetime),
])
def test_pg_typed_primary_keys_resume_exactly(pg, tmp_path, ddl, rows, key_type):
    admin, url = pg
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(ddl)
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO items VALUES (%s, %s)", rows)
    with rv_for(url, tmp_path, embedding_provider=FailOnce(fail_on_call=2)) as rv:
        rv.configure(root_table="items", text_fields=["label"])
        with pytest.raises(RuntimeError):
            rv.index(batch_size=2)
        cp = rv.store.checkpoint("items")
        assert cp.status == "running" and isinstance(cp.last_key[0], key_type)
        assert cp.last_key[0] == sorted(r[0] for r in rows)[1]
        resumed = rv.index(batch_size=2, resume=True)
        assert resumed.resumed and resumed.embedded == 3 and resumed.deleted == 0
        assert rv.store.count() == 5 and rv.store.checkpoint("items").status == "completed"
        assert rv.index(batch_size=2).unchanged == 5  # no duplicate or missing ids


def test_pg_batch_reads_one_snapshot(pg, tmp_path):
    """A change committed between a batch's root query and its related-row query is not seen."""
    admin, url = pg
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(SHOP)
    state = {"mutated": False}

    def mutate_between_queries(sql: str) -> None:
        if "FROM shipments" in sql and not state["mutated"]:
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute("UPDATE shipments SET delay_reason = 'flooded road' WHERE id = 502")
            state["mutated"] = True

    with rv_for(url, tmp_path, sql_validator=mutate_between_queries) as rv:
        rv.configure(root_table="orders", include_tables=["shipments"],
                     text_fields=["shipments.delay_reason"])
        rv.index(batch_size=10)
        assert state["mutated"]
        doc = next(h for h in rv.search("order", top_k=10) if h.source_pk == {"id": 1002})
        assert "carrier capacity shortage" in doc.text and "flooded" not in doc.text
        rv.index(batch_size=10)  # the next run sees the committed change
        doc = next(h for h in rv.search("order", top_k=10) if h.source_pk == {"id": 1002})
        assert "flooded road" in doc.text


def test_pg_concurrent_resume_rejected(pg, tmp_path):
    admin, url = pg
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(SHOP)
    with rv_for(url, tmp_path, embedding_provider=FailOnce(fail_on_call=2)) as rv:
        rv.configure(root_table="orders", text_fields=["status"])
        with pytest.raises(RuntimeError):
            rv.index(batch_size=2)

    class ResumedElsewhere(HashingEmbedding):
        def embed(self, texts):
            with rv_for(url, tmp_path) as other:
                other.configure(root_table="orders", text_fields=["status"])
                assert other.index(batch_size=2, resume=True).resumed
            return super().embed(texts)

    with rv_for(url, tmp_path, embedding_provider=ResumedElsewhere(256)) as rv:
        rv.configure(root_table="orders", text_fields=["status"])
        with pytest.raises(RunSupersededError):
            rv.index(batch_size=2, resume=True)
        assert rv.store.count() == 5 and rv.store.checkpoint("orders").status == "completed"
