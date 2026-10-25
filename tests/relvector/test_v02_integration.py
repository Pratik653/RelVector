"""v0.2 integration: incremental sync feeding the FAISS backend (no stale searchable vectors)."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from relvector import HashingEmbedding, RelVector

faiss = pytest.importorskip("faiss")

from relvector import FaissVectorStore  # noqa: E402

T0 = dt.datetime(2026, 1, 1, 12, 0, 0)


def ts(minutes: int) -> str:
    return (T0 + dt.timedelta(minutes=minutes)).isoformat(sep=" ")


@pytest.fixture
def tracked_db(tmp_path):
    path = tmp_path / "shop.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT NOT NULL,
                             deleted_at TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE shipments (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL
                                REFERENCES orders(id), delay_reason TEXT,
                                updated_at TEXT NOT NULL);
        """)
        conn.executemany("INSERT INTO orders VALUES (?,?,NULL,?)",
                         [(i, "delayed" if i % 2 else "delivered", ts(i - 60)) for i in range(1, 41)])
        conn.executemany("INSERT INTO shipments VALUES (?,?,?,?)",
                         [(100 + i, i, f"routine note {i}", ts(i - 60)) for i in range(1, 41)])
        conn.execute("UPDATE shipments SET delay_reason = 'volcanic ash closed the airport' "
                     "WHERE id = 105")
    conn.close()
    return path


def open_rv(db, index, **kw) -> RelVector:
    store = FaissVectorStore(index, ann_min_vectors=0, nlist=4, nprobe=4)  # force ANN
    rv = RelVector(f"sqlite:///{db}", embedding_provider=HashingEmbedding(128),
                   vector_store=store, **kw)
    rv.configure(root_table="orders", include_tables=["shipments"],
                 text_fields=["orders.status", "shipments.delay_reason"],
                 change_tracking={"orders": "updated_at", "shipments": "updated_at"},
                 soft_delete="deleted_at")
    return rv


def texts_for(rv: RelVector, query: str, k: int = 40) -> dict[int, str]:
    hits = rv.search(query, top_k=k)
    assert rv.store.last_search_mode == "ann"  # type: ignore[attr-defined]
    return {h.source_pk["id"]: h.text for h in hits}


def test_sync_propagates_updates_reassignments_and_deletes_to_faiss(tracked_db, tmp_path):
    index = tmp_path / "shop.rvindex"
    with open_rv(tracked_db, index) as rv:
        assert rv.index(batch_size=16).rows == 40
        assert "volcanic ash" in texts_for(rv, "volcanic ash closed the airport")[5]

        with sqlite3.connect(tracked_db) as conn:
            # Child update, child reassignment (105 moves from order 5 to 6), root soft delete.
            conn.execute("UPDATE shipments SET delay_reason = 'flooded rail line', "
                         f"updated_at = '{ts(10)}' WHERE id = 107")
            conn.execute(f"UPDATE shipments SET order_id = 6, updated_at = '{ts(11)}' "
                         "WHERE id = 105")
            conn.execute(f"UPDATE orders SET deleted_at = '{ts(12)}', updated_at = '{ts(12)}' "
                         "WHERE id = 9")
        conn.close()

        stats = rv.sync(batch_size=8, lookback=dt.timedelta(0))
        assert stats.mode == "sync" and stats.deleted == 1
        # Only affected roots: 7, 5 and 6 (old/new parent), 9, plus the rows sitting exactly at
        # the previous watermarks (re-read on purpose with >= so equal timestamps are not lost).
        assert stats.changed_rows == {"orders": 2, "shipments": 3}
        assert stats.embedded == 3 and stats.roots_rebuilt <= 6

        store = rv.store
        assert store._index.ntotal == store.count() == 39  # type: ignore[attr-defined]
        found = texts_for(rv, "volcanic ash closed the airport")
        assert "volcanic ash" in found[6]          # new parent gained the shipment
        assert "volcanic ash" not in found.get(5, "")  # old parent's stale text is gone
        assert 9 not in texts_for(rv, "delayed routine note 9")  # soft-deleted root unsearchable
        assert "flooded rail line" in texts_for(rv, "flooded rail line")[7]

    # Restart: the persisted FAISS index matches SQLite and is reused, not rebuilt.
    with open_rv(tracked_db, index) as rv:
        assert rv.store.last_rebuild_reason is None  # type: ignore[attr-defined]
        assert "volcanic ash" in texts_for(rv, "volcanic ash closed the airport")[6]
        assert rv.sync(batch_size=8, lookback=dt.timedelta(0)).embedded == 0


def test_faiss_selected_by_name_and_full_reindex_prunes(tracked_db, tmp_path):
    with RelVector(f"sqlite:///{tracked_db}", embedding_provider=HashingEmbedding(128),
                   vector_store="faiss", index_path=tmp_path / "i.rvindex") as rv:
        assert isinstance(rv.store, FaissVectorStore)
        rv.configure(root_table="orders", text_fields=["status"])
        rv.index(batch_size=10)
        with sqlite3.connect(tracked_db) as conn:  # a hard delete: only a full run sees it
            conn.execute("DELETE FROM shipments WHERE order_id = 3")
            conn.execute("DELETE FROM orders WHERE id = 3")
        conn.close()
        assert rv.index(batch_size=10).deleted == 1
        assert rv.store.count() == 39
        assert all(h.source_pk["id"] != 3 for h in rv.search("delayed", top_k=40))
