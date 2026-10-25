"""Chunked streaming search must match exact brute-force search, with bounded memory."""

from __future__ import annotations

import sqlite3
import tracemalloc

import numpy as np
import pytest

from relvector import IndexMismatchError, LocalVectorStore
from relvector.embeddings import normalize
from relvector.mapping import SemanticRecord
from relvector.store import Checkpoint

DIM = 16


def record(i: int, entity: str = "orders", status: str = "open") -> SemanticRecord:
    return SemanticRecord(
        vector_id=f"{entity}:[{i}]", entity=entity, source_table=entity, source_pk={"id": i},
        text=f"{entity} {i}", metadata={f"{entity}.status": status},
        references=[{"table": "shipments", "relation": "one_to_many", "pk": {"id": i * 10}}],
        truncated={}, mapping_version="1", content_hash=str(i),
    )


def build(path, vectors, records, chunk=4096) -> LocalVectorStore:
    store = LocalVectorStore(path, search_chunk_size=chunk)
    store.ensure_compatible("test-model", vectors.shape[1])
    cp = Checkpoint(records[0].entity, "run", None, "running", 0, "", "w")
    store.start_run(cp)
    for start in range(0, len(records), 500):
        store.write_batch(records[start:start + 500], vectors[start:start + 500], [], cp)
    return store


def exact(vectors, records, query, top_k, keep=lambda r: True):
    """Reference: score every matching vector at once, rank by (score desc, vector_id asc)."""
    q = normalize(query.reshape(1, -1))[0].astype(np.float64)
    m = normalize(vectors).astype(np.float64)
    hits = [(-(float(m[i] @ q)), r.vector_id) for i, r in enumerate(records) if keep(r)]
    return [(vid, -neg) for neg, vid in sorted(hits)[:top_k]]


@pytest.fixture
def corpus():
    rng = np.random.default_rng(7)
    n = 103  # deliberately not a multiple of any chunk size
    vectors = rng.normal(size=(n, DIM)).astype(np.float32)
    vectors[50] = vectors[3]  # exact duplicates: a tie that must break by vector_id
    vectors[90] = vectors[3]
    records = [record(i, status="delayed" if i % 3 == 0 else "open") for i in range(n)]
    return vectors, records, rng.normal(size=DIM).astype(np.float32)


@pytest.mark.parametrize("chunk", [1, 2, 7, 64, 10_000])
@pytest.mark.parametrize("top_k", [1, 3, 10, 103, 500])
def test_chunked_matches_exact(tmp_path, corpus, chunk, top_k):
    vectors, records, query = corpus
    with_ties = query.copy()
    with_ties[:] = vectors[3]  # top hits are the three identical vectors
    store = build(tmp_path / "i.rv", vectors, records, chunk)
    for q in (query, with_ties):
        got = store.search(q, top_k)
        want = exact(vectors, records, q, top_k)
        assert [h.vector_id for h in got] == [vid for vid, _ in want]
        assert np.allclose([h.score for h in got], [s for _, s in want], atol=1e-6)
    tied = [h.vector_id for h in store.search(with_ties, 3)]
    assert tied == sorted(["orders:[3]", "orders:[50]", "orders:[90]"])
    store.close()


@pytest.mark.parametrize("chunk", [1, 5, 4096])
def test_filters_are_applied_before_scoring(tmp_path, corpus, chunk):
    vectors, records, query = corpus
    others = [record(i, entity="customers") for i in range(20)]
    store = build(tmp_path / "i.rv", vectors, records, chunk)
    cp = Checkpoint("customers", "run2", None, "running", 0, "", "w")
    store.start_run(cp)
    store.write_batch(others, np.ones((20, DIM), dtype=np.float32), [], cp)

    got = store.search(query, 10, entity="orders", filters={"orders.status": "delayed"})
    want = exact(vectors, records, query, 10,
                 keep=lambda r: r.metadata["orders.status"] == "delayed")
    assert [h.vector_id for h in got] == [vid for vid, _ in want]
    assert all(h.metadata == {"orders.status": "delayed"} for h in got)
    assert got[0].references == [{"table": "shipments", "relation": "one_to_many",
                                  "pk": {"id": got[0].source_pk["id"] * 10}}]
    assert {h.entity for h in store.search(query, 200)} == {"orders", "customers"}
    assert {h.entity for h in store.search(query, 200, entity="customers")} == {"customers"}
    assert store.search(query, 5, filters={"orders.status": "missing"}) == []
    store.close()


def test_edge_cases(tmp_path, corpus):
    vectors, records, query = corpus
    empty = LocalVectorStore(tmp_path / "empty.rv")
    assert empty.search(query, 5) == []  # no dimension recorded yet
    empty.ensure_compatible("test-model", DIM)
    assert empty.search(query, 5) == []  # dimension known, no rows
    empty.close()

    store = build(tmp_path / "i.rv", vectors, records, chunk=8)
    with pytest.raises(ValueError, match="top_k"):
        store.search(query, 0)
    with pytest.raises(IndexMismatchError):
        store.search(np.ones(DIM + 1, dtype=np.float32), 3)
    zero = store.search(np.zeros(DIM, dtype=np.float32), 4)  # every score 0: order by id
    assert [h.vector_id for h in zero] == sorted(r.vector_id for r in records)[:4]
    assert all(h.score == 0.0 for h in zero)
    with pytest.raises(ValueError, match="search_chunk_size"):
        LocalVectorStore(tmp_path / "x.rv", search_chunk_size=0)
    store.close()

    with sqlite3.connect(tmp_path / "i.rv") as conn:  # a truncated blob is detected, not misread
        conn.execute("UPDATE rv_records SET vector = x'00' WHERE vector_id = 'orders:[7]'")
    conn.close()
    store = LocalVectorStore(tmp_path / "i.rv", search_chunk_size=8)
    with pytest.raises(IndexMismatchError, match="orders:\\[7\\]"):
        store.search(query, 3)
    store.close()


def test_search_memory_is_bounded_by_chunk_not_index(tmp_path):
    n, dim, chunk = 20_000, 64, 256
    vectors = np.random.default_rng(1).normal(size=(n, dim)).astype(np.float32)
    store = build(tmp_path / "big.rv", vectors, [record(i) for i in range(n)], chunk)
    full_matrix = n * dim * 4  # ~5.1 MB: what the previous implementation materialised twice
    query = vectors[123]
    tracemalloc.start()
    try:
        hits = store.search(query, 10)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert hits[0].vector_id == "orders:[123]"
    assert peak < full_matrix / 5, f"peak {peak} bytes vs full matrix {full_matrix}"
    store.close()
