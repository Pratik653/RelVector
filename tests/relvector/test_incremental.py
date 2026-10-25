"""Incremental sync via change-tracking columns (deterministic hashing embeddings)."""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from pathlib import Path

import pytest

from relvector import HashingEmbedding, MappingError, RelVector, RunSupersededError
from relvector.sync import SyncUnavailableError

BASE = dt.datetime(2026, 1, 1, 9, 0, 0)


def ts(minutes: float) -> str:
    return (BASE + dt.timedelta(minutes=minutes)).isoformat(sep=" ")


SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, segment TEXT, updated_at TEXT);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), status TEXT NOT NULL,
    updated_at TEXT, deleted_at TEXT
);
CREATE TABLE shipments (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), delay_reason TEXT,
    updated_at TEXT
);
"""

TRACKING = {"orders": "updated_at", "shipments": "updated_at", "customers": "updated_at"}
TEMPLATES = {"orders": "Order {id} is {status}.", "shipments": "Shipment {id}: {delay_reason}.",
             "customers": "Customer segment {segment}."}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "shop.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO customers VALUES (?,?,?)",
                         [(1, "retail", ts(0)), (2, "wholesale", ts(1))])
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,NULL)", [
            (1001, 1, "delivered", ts(2)), (1002, 1, "delayed", ts(3)),
            (1003, 2, "delayed", ts(4)), (1004, None, "processing", ts(5)),
        ])
        conn.executemany("INSERT INTO shipments VALUES (?,?,?,?)", [
            (501, 1001, "on time", ts(6)), (502, 1002, "carrier capacity shortage", ts(7)),
            (503, 1003, "truck breakdown", ts(8)),
        ])
    conn.close()
    return path


def write(db: Path, sql: str, *params: object) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(sql, params)
    conn.close()


class CountingEmbedding(HashingEmbedding):
    def __init__(self, fail_on_call: int | None = None) -> None:
        super().__init__(256)
        self.texts: list[str] = []
        self.calls = 0
        self.fail_on_call = fail_on_call

    def embed(self, texts):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("embedding service down")
        self.texts.extend(texts)
        return super().embed(texts)


def make_rv(db: Path, tmp_path: Path, provider=None, *, customers: bool = False,
            tracking=None, **kw) -> RelVector:
    rv = RelVector(f"sqlite:///{db}", embedding_provider=provider or CountingEmbedding(),
                   index_path=tmp_path / "i.rv")
    include = ["shipments", *(["customers"] if customers else [])]
    text = ["orders.status", "shipments.delay_reason",
            *(["customers.segment"] if customers else [])]
    if tracking is None:
        tracking = {t: c for t, c in TRACKING.items() if t in ("orders", *include)}
    rv.configure(root_table="orders", include_tables=include, text_fields=text,
                 metadata_fields=["orders.status"],
                 templates={t: v for t, v in TEMPLATES.items() if t in ("orders", *include)},
                 change_tracking=tracking, **kw)
    return rv


def doc(rv: RelVector, order_id: int) -> str | None:
    row = rv.store._conn.execute(  # type: ignore[attr-defined]
        "SELECT text FROM rv_records WHERE vector_id = ?", (f"orders:[{order_id}]",)).fetchone()
    return None if row is None else row[0]


def watermarks(rv: RelVector) -> dict:
    cp = rv.store.checkpoint("orders")
    assert cp is not None and cp.state is not None
    return cp.state["watermarks"]


NO_LOOKBACK = dt.timedelta(0)


# --- configuration and preconditions ------------------------------------------------------


def test_tracking_config_does_not_change_fingerprint_or_hashes(db, tmp_path):
    with make_rv(db, tmp_path, tracking={}) as rv:
        plain = rv.mapping.fingerprint
        rv.index()
        hashes = rv.store.content_hashes([f"orders:[{i}]" for i in (1001, 1002, 1003, 1004)])
    with make_rv(db, tmp_path) as rv:
        assert rv.mapping.fingerprint == plain
        assert rv.mapping.tracking == {"orders": "updated_at", "shipments": "updated_at"}
        stats = rv.index()
        assert stats.embedded == 0 and stats.unchanged == 4  # tracking alone re-embeds nothing
        assert rv.store.content_hashes(list(hashes)) == hashes


def test_invalid_tracking_config_is_rejected(db, tmp_path):
    with pytest.raises(MappingError, match="neither the root table"):
        make_rv(db, tmp_path, tracking={"customers": "updated_at"})
    with pytest.raises(Exception, match="no column"):
        make_rv(db, tmp_path, tracking={"orders": "modified"})
    with pytest.raises(MappingError, match="soft_delete must be a column of the root"):
        make_rv(db, tmp_path, soft_delete="shipments.updated_at")


def test_missing_tracking_for_a_mapped_table_fails_clearly(db, tmp_path):
    with make_rv(db, tmp_path, tracking={"orders": "updated_at"}) as rv:
        rv.index()
        with pytest.raises(MappingError, match="missing for shipments"):
            rv.sync()
        # Only an explicit opt-in falls back to the full reconciliation.
        stats = rv.sync(full_fallback=True)
        assert stats.mode == "full" and "shipments" in (stats.reason or "")
        assert stats.unchanged == 4


def test_sync_before_any_index_errors(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        with pytest.raises(SyncUnavailableError, match="run index"):
            rv.sync()
        stats = rv.sync(full_fallback=True)
        assert stats.mode == "full" and rv.store.count() == 4
        assert rv.sync(lookback=NO_LOOKBACK).mode == "sync"


def test_index_without_tracking_leaves_no_watermarks(db, tmp_path):
    with make_rv(db, tmp_path, tracking={}) as rv:
        rv.index()
    with make_rv(db, tmp_path) as rv, pytest.raises(SyncUnavailableError, match="run index"):
        rv.sync()


def test_changed_mapping_or_tracking_requires_full_index(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
    with make_rv(db, tmp_path, version="2") as rv, pytest.raises(SyncUnavailableError,
                                                                  match="mapping"):
        rv.sync()
    with make_rv(db, tmp_path, soft_delete="deleted_at") as rv:
        with pytest.raises(SyncUnavailableError, match="soft_delete changed"):
            rv.sync()
        rv.index()
        rv.sync()


# --- change propagation --------------------------------------------------------------------


def test_full_index_then_sync_processes_only_later_changes(db, tmp_path):
    provider = CountingEmbedding()
    with make_rv(db, tmp_path, provider) as rv:
        rv.index()
        assert watermarks(rv) == {"orders": ts(5), "shipments": ts(8)}
        provider.texts.clear()
        noop = rv.sync(lookback=NO_LOOKBACK)
        # Only rows at exactly the watermark are re-read (>=), and nothing is re-embedded.
        assert noop.changed_rows == {"orders": 1, "shipments": 1}
        assert noop.embedded == 0 and noop.unchanged == 2 and provider.texts == []

        write(db, "UPDATE orders SET status = 'cancelled', updated_at = ? WHERE id = 1002",
              ts(30))
        stats = rv.sync(lookback=NO_LOOKBACK)
        # The changed row plus the row still sitting exactly at the old watermark (>=).
        assert stats.changed_rows == {"orders": 2, "shipments": 1}
        assert stats.embedded == 1 and provider.texts == [doc(rv, 1002)]
        assert "cancelled" in (doc(rv, 1002) or "")
        assert watermarks(rv)["orders"] == ts(30)
        assert rv.store.checkpoint("orders").status == "completed"


def test_changes_during_full_scan_are_picked_up_by_next_sync(db, tmp_path):
    class ChangesSourceDuringScan(CountingEmbedding):
        def embed(self, texts):
            if self.calls == 0:  # first batch: another writer updates a not-yet-scanned row
                write(db, "UPDATE orders SET status = 'returned', updated_at = ? "
                          "WHERE id = 1001", ts(40))
            return super().embed(texts)

    with make_rv(db, tmp_path, ChangesSourceDuringScan()) as rv:
        rv.index(batch_size=2)
        # 1001 was scanned before the update; the watermark predates the scan.
        assert "delivered" in (doc(rv, 1001) or "")
        assert watermarks(rv)["orders"] == ts(5)
        stats = rv.sync(lookback=NO_LOOKBACK)
        assert stats.embedded == 1 and "returned" in (doc(rv, 1001) or "")


def test_child_insert_and_update_rebuild_the_parent(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
        write(db, "INSERT INTO shipments VALUES (504, 1004, 'customs hold', ?)", ts(20))
        write(db, "UPDATE shipments SET delay_reason = 'port congestion', updated_at = ? "
                  "WHERE id = 503", ts(21))
        stats = rv.sync(lookback=NO_LOOKBACK)
        assert stats.changed_rows["shipments"] == 2 and stats.embedded == 2
        assert "customs hold" in (doc(rv, 1004) or "")
        assert "port congestion" in (doc(rv, 1003) or "")
        assert "truck breakdown" not in (doc(rv, 1003) or "")
        refs = rv.store.referencing("orders", "shipments", [{"id": 504}])
        assert refs == {"orders:[1004]": {"id": 1004}}


def test_child_reassignment_updates_old_and_new_parent(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
        write(db, "UPDATE shipments SET order_id = 1001, updated_at = ? WHERE id = 503", ts(20))
        stats = rv.sync(lookback=NO_LOOKBACK)
        assert stats.embedded == 2
        assert "truck breakdown" in (doc(rv, 1001) or "")
        assert "truck breakdown" not in (doc(rv, 1003) or "")
        assert "No related shipments." in (doc(rv, 1003) or "")
        assert rv.store.referencing("orders", "shipments", [{"id": 503}]) == {
            "orders:[1001]": {"id": 1001}}


def test_many_to_one_parent_change_rebuilds_all_referencing_roots(db, tmp_path):
    with make_rv(db, tmp_path, customers=True) as rv:
        rv.index()
        write(db, "UPDATE customers SET segment = 'enterprise', updated_at = ? WHERE id = 1",
              ts(20))
        stats = rv.sync(batch_size=1, lookback=NO_LOOKBACK)  # fan-out paginated by batch
        assert stats.changed_rows["customers"] == 2 and stats.embedded == 2  # + row at watermark
        assert "enterprise" in (doc(rv, 1001) or "") and "enterprise" in (doc(rv, 1002) or "")
        assert "wholesale" in (doc(rv, 1003) or "")


def test_equal_timestamps_and_lookback_window(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
        # Equal timestamp: committed after the sync read ts(8), with the same value.
        write(db, "INSERT INTO shipments VALUES (504, 1004, 'customs hold', ?)", ts(8))
        rv.sync(lookback=NO_LOOKBACK)
        assert "customs hold" in (doc(rv, 1004) or "")
        # Late commit: timestamp taken 2 minutes before the watermark. Without a lookback it is
        # missed (documented); a lookback window covering it finds it.
        write(db, "UPDATE shipments SET delay_reason = 'late update', updated_at = ? "
                  "WHERE id = 501", ts(6))
        missed = rv.sync(lookback=NO_LOOKBACK)
        assert missed.embedded == 0 and "late update" not in (doc(rv, 1001) or "")
        caught = rv.sync(lookback=dt.timedelta(minutes=5))
        assert caught.embedded == 1 and "late update" in (doc(rv, 1001) or "")
        again = rv.sync(lookback=dt.timedelta(minutes=5))  # re-reading the window is idempotent
        assert again.embedded == 0 and again.unchanged >= 1


def test_root_soft_delete_removes_record(db, tmp_path):
    with make_rv(db, tmp_path, soft_delete="deleted_at") as rv:
        write(db, "UPDATE orders SET deleted_at = ? WHERE id = 1004", ts(5))
        rv.index()
        assert rv.store.count() == 3 and doc(rv, 1004) is None  # full index skips it too
        write(db, "UPDATE orders SET deleted_at = ?, updated_at = ? WHERE id = 1002",
              ts(20), ts(20))
        stats = rv.sync(lookback=NO_LOOKBACK)
        assert stats.deleted == 1 and doc(rv, 1002) is None and rv.store.count() == 2


def test_hard_delete_needs_full_index_reconciliation(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
        write(db, "DELETE FROM orders WHERE id = 1004")
        assert rv.sync(lookback=NO_LOOKBACK).deleted == 0  # invisible to timestamps
        assert doc(rv, 1004) is not None
        assert rv.index().deleted == 1 and doc(rv, 1004) is None
        assert rv.sync(lookback=NO_LOOKBACK).mode == "sync"  # watermarks survive the full run


def test_rebuilt_root_that_no_longer_exists_is_deleted(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
        write(db, "DELETE FROM shipments WHERE id = 503")
        write(db, "DELETE FROM orders WHERE id = 1003")
        # A child row pointing at the deleted order is touched: the order is checked and gone.
        write(db, "INSERT INTO shipments VALUES (509, 1003, 'orphan', ?)", ts(20))
        stats = rv.sync(lookback=NO_LOOKBACK)
        assert stats.deleted == 1 and doc(rv, 1003) is None


def test_interrupted_sync_resumes_and_never_advances_past_uncommitted_work(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
    for i, oid in enumerate((1001, 1002, 1003)):
        write(db, "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
              f"status{i}", ts(20 + i), oid)

    provider = CountingEmbedding(fail_on_call=2)
    with make_rv(db, tmp_path, provider) as rv:
        with pytest.raises(RuntimeError):
            rv.sync(batch_size=1, lookback=NO_LOOKBACK)
        cp = rv.store.checkpoint("orders")
        # Batch 1 (1001 at ts(20)) committed with its watermark; batch 2 failed before writing.
        assert cp.status == "running" and cp.state["watermarks"]["orders"] == ts(20)
        assert "status0" in (doc(rv, 1001) or "") and "status1" not in (doc(rv, 1002) or "")
        # A full index cannot resume an interrupted sync as if it were a full scan.
        stats = rv.sync(batch_size=1, lookback=NO_LOOKBACK)
        assert stats.embedded == 2  # 1001 re-read at the watermark (>=) but not re-embedded
        assert "status1" in (doc(rv, 1002) or "") and "status2" in (doc(rv, 1003) or "")
        assert rv.store.checkpoint("orders").status == "completed"
        assert watermarks(rv)["orders"] == ts(22)


def test_index_resume_after_interrupted_sync_starts_a_fresh_full_run(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
    write(db, "UPDATE orders SET status = 'x', updated_at = ? WHERE id = 1001", ts(20))
    with (make_rv(db, tmp_path, CountingEmbedding(fail_on_call=1)) as rv,
          pytest.raises(RuntimeError)):
        rv.sync(lookback=NO_LOOKBACK)
    with make_rv(db, tmp_path) as rv:
        stats = rv.index(resume=True)
        assert not stats.resumed and stats.rows == 4 and "is x" in (doc(rv, 1001) or "")
        assert watermarks(rv)["orders"] == ts(20)


def test_full_index_supersedes_running_sync(db, tmp_path):
    with make_rv(db, tmp_path) as rv:
        rv.index()
    write(db, "UPDATE orders SET status = 'x', updated_at = ? WHERE id = 1001", ts(20))
    write(db, "UPDATE orders SET status = 'y', updated_at = ? WHERE id = 1002", ts(21))

    class IndexesMeanwhile(CountingEmbedding):
        def embed(self, texts):
            if self.calls == 0:
                with make_rv(db, tmp_path) as other:
                    other.index()
            return super().embed(texts)

    with make_rv(db, tmp_path, IndexesMeanwhile()) as rv:
        with pytest.raises(RunSupersededError):
            rv.sync(batch_size=1, lookback=NO_LOOKBACK)
        cp = rv.store.checkpoint("orders")
        assert cp.status == "completed" and cp.state["watermarks"]["orders"] == ts(21)


# --- PostgreSQL (timestamptz tracking) -----------------------------------------------------

PG_SHOP = """
CREATE TABLE orders (id uuid PRIMARY KEY, status text NOT NULL,
                     updated_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE shipments (id integer PRIMARY KEY, order_id uuid NOT NULL REFERENCES orders(id),
                        delay_reason text,
                        updated_at timestamptz NOT NULL DEFAULT clock_timestamp());
"""
A = uuid.UUID(int=1)
B = uuid.UUID(int=2)


def pg_rv(url: str, tmp_path: Path, provider=None) -> RelVector:
    rv = RelVector(url, embedding_provider=provider or CountingEmbedding(),
                   index_path=tmp_path / "pg.rv")
    rv.configure(root_table="orders", include_tables=["shipments"],
                 text_fields=["orders.status", "shipments.delay_reason"],
                 change_tracking={"orders": "updated_at", "shipments": "updated_at"})
    return rv


def pg_doc(rv: RelVector, key: uuid.UUID) -> str | None:
    row = rv.store._conn.execute(  # type: ignore[attr-defined]
        "SELECT text FROM rv_records WHERE vector_id = ?", (f'orders:["{key}"]',)).fetchone()
    return None if row is None else row[0]


@pytest.mark.postgres
def test_pg_timestamptz_sync_reassignment_and_typed_watermarks(pg, tmp_path):
    import psycopg

    admin, url = pg
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(PG_SHOP)
        conn.execute("INSERT INTO orders (id, status) VALUES (%s, 'delayed'), (%s, 'ok')",
                     (A, B))
        conn.execute("INSERT INTO shipments (id, order_id, delay_reason) VALUES "
                     "(1, %s, 'truck breakdown'), (2, %s, 'none')", (A, B))
    provider = CountingEmbedding()
    with pg_rv(url, tmp_path, provider) as rv:
        rv.index()
        wm = watermarks(rv)
        assert isinstance(wm["orders"], dt.datetime) and wm["orders"].tzinfo is not None
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("UPDATE shipments SET order_id = %s, updated_at = clock_timestamp() "
                         "WHERE id = 1", (B,))
        provider.texts.clear()
        stats = rv.sync()
        assert stats.embedded == 2 and len(provider.texts) == 2
        assert "truck breakdown" in (pg_doc(rv, B) or "")
        assert "truck breakdown" not in (pg_doc(rv, A) or "")
        assert watermarks(rv)["shipments"] > wm["shipments"]
        assert rv.sync().embedded == 0  # the default 5-minute lookback re-reads, idempotently


@pytest.mark.postgres
def test_pg_interrupted_sync_then_rerun(pg, tmp_path):
    import psycopg

    admin, url = pg
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(PG_SHOP)
        conn.execute("INSERT INTO orders (id, status) VALUES (%s, 'a'), (%s, 'b')", (A, B))
    with pg_rv(url, tmp_path) as rv:
        rv.index()
        before = watermarks(rv)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("UPDATE orders SET status = status || '-changed', "
                     "updated_at = clock_timestamp()")
    with pg_rv(url, tmp_path, CountingEmbedding(fail_on_call=1)) as rv:
        with pytest.raises(RuntimeError):
            rv.sync(lookback=NO_LOOKBACK)
        assert watermarks(rv) == before  # nothing committed, nothing advanced
    with pg_rv(url, tmp_path) as rv:
        stats = rv.sync(lookback=NO_LOOKBACK)
        assert stats.embedded == 2
        assert "a-changed" in (pg_doc(rv, A) or "") and "b-changed" in (pg_doc(rv, B) or "")
