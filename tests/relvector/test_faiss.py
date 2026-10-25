"""FAISS ANN backend: exact re-ranking, mutations, persistence, recovery and fallbacks."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

from relvector import HashingEmbedding, IndexMismatchError, LocalVectorStore, RelVector
from relvector.errors import RelVectorError
from relvector.mapping import SemanticRecord
from relvector.store import Checkpoint

faiss = pytest.importorskip("faiss")
from relvector.faiss_store import FaissVectorStore  # noqa: E402

DIM = 16


def record(i: int, entity: str = "orders", status: str = "open", h: str = "") -> SemanticRecord:
    return SemanticRecord(
        vector_id=f"{entity}:[{i}]", entity=entity, source_table=entity, source_pk={"id": i},
        text=f"{entity} {i}", metadata={f"{entity}.status": status},
        references=[], truncated={}, mapping_version="1", content_hash=h or str(i),
    )


def clustered(n: int, seed: int = 3, clusters: int = 20) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(clusters, DIM))
    return (centres[rng.integers(0, clusters, n)]
            + 0.1 * rng.normal(size=(n, DIM))).astype(np.float32)


def run(store, entity="orders", run_id="run") -> Checkpoint:
    cp = Checkpoint(entity, run_id, None, "running", 0, "", "w")
    store.start_run(cp)
    return cp


def build(path, vectors, entity="orders", **kw) -> tuple[FaissVectorStore, Checkpoint]:
    kw.setdefault("ann_min_vectors", 0)
    store = FaissVectorStore(path, **kw)
    store.ensure_compatible("test-model", DIM)
    cp = run(store, entity)
    recs = [record(i, entity) for i in range(len(vectors))]
    for s in range(0, len(recs), 300):
        store.write_batch(recs[s:s + 300], vectors[s:s + 300], [], cp)
    store.finish_run(cp, prune=False)  # builds and saves the FAISS index
    return store, run(store, entity, "next")  # a running checkpoint for further writes


def exact(store, q, k, **kw):
    return [(h.vector_id, h.score) for h in LocalVectorStore.search(store, q, k, **kw)]


def ann(store, q, k, **kw):
    hits = store.search(q, k, **kw)
    assert store.last_search_mode == "ann", store.last_search_reason
    return [(h.vector_id, h.score) for h in hits]


def test_core_import_does_not_import_faiss():
    code = ("import sys, relvector, relvector.faiss_store; "
            "assert 'faiss' not in sys.modules, 'faiss imported eagerly'")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_missing_faiss_gives_install_hint(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faiss", None)  # makes "import faiss" raise ImportError
    with pytest.raises(RelVectorError, match=r"relvector\[faiss\]"):
        FaissVectorStore(tmp_path / "i.rv")


@pytest.mark.parametrize("top_k", [1, 5, 25])
def test_ann_equals_exact_on_clustered_data(tmp_path, top_k):
    vectors = clustered(1200)
    store, _ = build(tmp_path / "i.rv", vectors)
    rng = np.random.default_rng(11)
    for qi in rng.integers(0, len(vectors), 10):
        q = vectors[qi] + 0.01 * rng.normal(size=DIM).astype(np.float32)
        got = ann(store, q, top_k)
        assert got == exact(store, q, top_k)  # same ids, same order, identical exact scores
    assert "approximate" in store.last_search_reason
    store.close()


def test_full_probe_equals_exact_on_random_data_including_ties(tmp_path):
    rng = np.random.default_rng(5)
    vectors = rng.normal(size=(500, DIM)).astype(np.float32)
    vectors[70] = vectors[300] = vectors[3]
    store, _ = build(tmp_path / "i.rv", vectors, nprobe=10_000, oversample=8)
    for q in (rng.normal(size=DIM).astype(np.float32), vectors[3]):
        assert ann(store, q, 10) == exact(store, q, 10)
    assert [v for v, _ in ann(store, vectors[3], 3)] == ["orders:[300]", "orders:[3]",
                                                         "orders:[70]"]
    store.close()


def test_upsert_moves_vector_and_delete_and_prune_leave_no_stale_hits(tmp_path):
    vectors = clustered(600)
    store, cp = build(tmp_path / "i.rv", vectors)
    target = clustered(1, seed=99)[0] * 5  # far from every existing cluster
    store.write_batch([record(7, h="changed")], target.reshape(1, -1), [], cp)
    assert ann(store, target, 1)[0][0] == "orders:[7]"
    assert store._index.ntotal == 600  # replaced, not duplicated
    # Delete it: it must disappear from ANN results.
    assert store.delete_records(["orders:[7]"], cp) == 1
    assert "orders:[7]" not in [v for v, _ in ann(store, target, 10)]
    assert store._index.ntotal == 599
    # Re-insert (new rowid), then a new run that only sees records 0..99 and prunes the rest.
    store.write_batch([record(7, h="back")], target.reshape(1, -1), [], cp)
    assert ann(store, target, 1)[0][0] == "orders:[7]"
    store.finish_run(cp, prune=False)
    cp2 = run(store, run_id="run2")
    store.write_batch([], np.empty((0, DIM), np.float32), [f"orders:[{i}]" for i in range(100)],
                      cp2)
    assert store.finish_run(cp2, prune=True) == 500
    assert store._index.ntotal == store.count() == 100
    got = ann(store, target, 10)
    assert all(int(v[8:-1]) < 100 for v, _ in got)
    assert got == exact(store, target, 10)
    assert not store.dirty_path.exists()  # finish_run saved the index
    store.close()


def test_restart_loads_persisted_index_without_rebuild(tmp_path):
    vectors = clustered(800)
    store, _ = build(tmp_path / "i.rv", vectors)
    q = vectors[42]
    before = ann(store, q, 5)
    store.close()
    assert store.index_path.exists() and store.meta_path.exists()
    assert not store.dirty_path.exists()
    reopened = FaissVectorStore(tmp_path / "i.rv", ann_min_vectors=0)
    assert reopened.last_rebuild_reason is None  # loaded, not rebuilt
    assert ann(reopened, q, 5) == before
    reopened.close()


def _crashed_store(tmp_path):
    """A store that committed to SQLite but 'crashed' before saving the FAISS file."""
    vectors = clustered(700)
    store, cp2 = build(tmp_path / "i.rv", vectors)
    target = clustered(1, seed=123)[0] * 5
    store.write_batch([record(9999, h="new")], target.reshape(1, -1), [], cp2)
    assert store.dirty_path.exists()
    LocalVectorStore.close(store)  # no flush: simulates a crash after the SQLite commit
    return target


def test_dirty_marker_forces_rebuild(tmp_path):
    target = _crashed_store(tmp_path)
    store = FaissVectorStore(tmp_path / "i.rv", ann_min_vectors=0)
    assert "dirty" in store.last_rebuild_reason
    assert not store.dirty_path.exists()
    assert ann(store, target, 1)[0][0] == "orders:[9999]"
    store.close()


@pytest.mark.parametrize("damage, reason", [
    ("corrupt", "unreadable"), ("missing", "no FAISS index file"),
    ("sidecar", "unreadable"), ("model", "model mismatch"), ("dimension", "model mismatch"),
])
def test_damaged_or_mismatched_files_are_rebuilt(tmp_path, damage, reason):
    vectors = clustered(500)
    store, _ = build(tmp_path / "i.rv", vectors)
    store.close()
    if damage == "corrupt":
        store.index_path.write_bytes(b"not a faiss index")
    elif damage == "missing":
        store.index_path.unlink()
    elif damage == "sidecar":
        store.meta_path.write_text("{truncated", encoding="utf-8")
    else:
        meta = json.loads(store.meta_path.read_text(encoding="utf-8"))
        meta["model_id" if damage == "model" else "dimension"] = (
            "other-model" if damage == "model" else 8)
        store.meta_path.write_text(json.dumps(meta), encoding="utf-8")
    reopened = FaissVectorStore(tmp_path / "i.rv", ann_min_vectors=0)
    assert reason in reopened.last_rebuild_reason
    assert ann(reopened, vectors[10], 5) == exact(reopened, vectors[10], 5)
    reopened.close()


def test_sqlite_changed_while_faiss_closed_or_by_other_connection(tmp_path):
    vectors = clustered(500)
    store, cp = build(tmp_path / "i.rv", vectors)
    store.finish_run(cp, prune=False)
    store.close()
    target = clustered(1, seed=7)[0] * 5
    # A plain local store (no FAISS awareness) changes a vector in place (same rowid).
    plain = LocalVectorStore(tmp_path / "i.rv")
    cp2 = run(plain, run_id="run2")
    plain.write_batch([record(3, h="x")], target.reshape(1, -1), [], cp2)
    plain.close()
    reopened = FaissVectorStore(tmp_path / "i.rv", ann_min_vectors=0)
    assert "out of sync" in reopened.last_rebuild_reason
    assert ann(reopened, target, 1)[0][0] == "orders:[3]"
    # Another connection writes while the FAISS store is open: detected and rebuilt.
    other = LocalVectorStore(tmp_path / "i.rv")
    target2 = -target
    other.write_batch([record(4, h="y")], target2.reshape(1, -1), [], cp2)
    other.delete_records(["orders:[3]"], cp2)
    other.close()
    got = ann(reopened, target2, 3)
    assert "another connection" in reopened.last_rebuild_reason
    assert got[0][0] == "orders:[4]" and "orders:[3]" not in [v for v, _ in got]
    reopened.close()


def test_dimension_mismatch_is_rejected(tmp_path):
    store, _ = build(tmp_path / "i.rv", clustered(100))
    with pytest.raises(IndexMismatchError):
        store.ensure_compatible("test-model", DIM + 1)
    with pytest.raises(IndexMismatchError):
        store.search(np.ones(DIM + 1, np.float32), 3)
    store.close()


def test_filters_and_multi_entity_fall_back_to_exact(tmp_path):
    vectors = clustered(400)
    store, _ = build(tmp_path / "i.rv", vectors)
    q = vectors[5]
    ann(store, q, 3, entity="orders")  # single-entity index: ANN can answer an entity query
    store.search(q, 3, filters={"orders.status": "open"})
    assert store.last_search_mode == "exact" and "filters" in store.last_search_reason
    cp2 = run(store, "customers")
    store.write_batch([record(i, "customers") for i in range(30)], clustered(30, seed=8), [], cp2)
    got = store.search(q, 5, entity="orders")
    assert store.last_search_mode == "exact" and "other entities" in store.last_search_reason
    assert [(h.vector_id, h.score) for h in got] == exact(store, q, 5, entity="orders")
    ann(store, q, 5)  # no entity filter: ANN over all entities
    store.close()


def test_small_index_searches_exactly_and_builds_nothing(tmp_path):
    store, _ = build(tmp_path / "i.rv", clustered(200), ann_min_vectors=1000)
    hits = store.search(clustered(1, seed=1)[0], 3)
    assert len(hits) == 3
    assert store.last_search_mode == "exact" and "ann_min_vectors" in store.last_search_reason
    assert store._index is None and not store.index_path.exists()
    store.close()


def test_growth_triggers_retrain_and_explicit_rebuild(tmp_path):
    vectors = clustered(1000)
    store, cp = build(tmp_path / "i.rv", vectors[:100])
    assert store._trained_on == 100
    recs = [record(i) for i in range(100, 1000)]
    store.write_batch(recs, vectors[100:], [], cp)
    ann(store, vectors[500], 5)
    assert "retraining" in store.last_rebuild_reason and store._trained_on == 1000
    store.rebuild()
    assert store.last_rebuild_reason == "explicit rebuild"
    assert ann(store, vectors[500], 5) == exact(store, vectors[500], 5)
    store.close()


def test_end_to_end_through_relvector(shop_db, tmp_path):
    def rv(path, store=None):
        return RelVector(f"sqlite:///{shop_db}", embedding_provider=HashingEmbedding(256),
                         index_path=path, vector_store=store or LocalVectorStore(path))

    def configure(r):
        r.configure(root_table="orders", include_tables=["shipments"],
                    text_fields=["orders.status", "shipments.delay_reason"],
                    metadata_fields=["orders.status"])

    query = "orders delayed by a truck breakdown"
    with rv(tmp_path / "local.rv") as local:
        configure(local)
        local.index()
        want = local.search(query, top_k=3)
    fs = FaissVectorStore(tmp_path / "f.rv", ann_min_vectors=0)
    with rv(tmp_path / "f.rv", fs) as r:
        configure(r)
        r.index()
        got = r.search(query, top_k=3)
        assert fs.last_search_mode == "ann"
        assert got[0].vector_id == want[0].vector_id == "orders:[1003]"
        assert got[0].score == pytest.approx(want[0].score)
        with sqlite3.connect(shop_db) as conn:
            conn.execute("DELETE FROM shipments WHERE order_id = 1003")
            conn.execute("DELETE FROM orders WHERE id = 1003")
            conn.execute("UPDATE shipments SET delay_reason = 'truck breakdown' WHERE id = 504")
        conn.close()
        r.index()
        got = r.search(query, top_k=10)
        assert fs.last_search_mode == "ann"
        ids = [h.vector_id for h in got]
        assert "orders:[1003]" not in ids and ids[0] == "orders:[1005]"
        assert fs._index.ntotal == fs.count() == 4
    reopened = FaissVectorStore(tmp_path / "f.rv", ann_min_vectors=0)
    assert reopened.last_rebuild_reason is None
    reopened.close()
