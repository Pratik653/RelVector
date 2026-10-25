"""Persistent local vector store: one SQLite file holding vectors, metadata and checkpoints.

Vectors are stored as raw little-endian float32 blobs and read back with ``numpy.frombuffer``;
metadata is JSON. Nothing is ever unpickled, so opening an index file cannot execute code.

Search is exact cosine similarity, streamed from disk in fixed-size chunks while keeping only
the best ``top_k`` hits, so memory stays bounded however large the index is. Time is still
linear in the number of (filtered) vectors per query; very large or latency-sensitive
workloads need an ANN backend implementing :class:`VectorStore`.
"""

from __future__ import annotations

import datetime as dt
import heapq
import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from relvector.embeddings import Vectors, normalize
from relvector.errors import IndexMismatchError, RelVectorError, RunSupersededError
from relvector.mapping import SemanticRecord


@dataclass(frozen=True)
class SearchResult:
    vector_id: str
    score: float
    text: str
    entity: str
    source_table: str
    source_pk: dict[str, Any]
    metadata: dict[str, Any]
    references: list[dict[str, Any]]
    truncated: dict[str, int]

    def __str__(self) -> str:
        return f"[{self.score:.3f}] {self.source_table} {self.source_pk}: {self.text}"


@dataclass(frozen=True)
class Checkpoint:
    entity: str
    run_id: str
    last_key: list[Any] | None
    status: str
    processed: int
    fingerprint: str = ""
    owner: str = ""


class VectorStore(Protocol):
    """Adapter interface for vector backends."""

    def ensure_compatible(self, model_id: str, dimension: int) -> None: ...
    def content_hashes(self, vector_ids: Sequence[str]) -> dict[str, str]: ...
    def start_run(self, checkpoint: Checkpoint) -> None: ...
    def resume_run(self, checkpoint: Checkpoint) -> None: ...
    def write_batch(self, records: Sequence[SemanticRecord], vectors: Vectors,
                    unchanged_ids: Sequence[str], checkpoint: Checkpoint) -> None: ...
    def finish_run(self, checkpoint: Checkpoint, *, prune: bool) -> int: ...
    def checkpoint(self, entity: str) -> Checkpoint | None: ...
    def search(self, vector: Vectors, top_k: int, *, entity: str | None = None,
               filters: Mapping[str, Any] | None = None) -> list[SearchResult]: ...
    def count(self, entity: str | None = None) -> int: ...
    def close(self) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rv_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rv_records (
    vector_id TEXT PRIMARY KEY,
    entity TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_pk TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata TEXT NOT NULL,
    refs TEXT NOT NULL,
    truncated TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    run_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS rv_records_entity_run ON rv_records (entity, run_id);
CREATE TABLE IF NOT EXISTS rv_checkpoints (
    entity TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    last_key TEXT,
    status TEXT NOT NULL,
    processed INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    fingerprint TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT ''
);
"""

_FORMAT_VERSION = "1"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


# Checkpoint keys keep their Python type through JSON so that, on resume, ``WHERE pk > :last``
# binds the same type the column holds and the database compares it with the column's own
# ordering (a date compared as a date, a UUID as a UUID), never as text.
_KEY_TYPES: list[tuple[str, type, Any, Any]] = [
    ("datetime", dt.datetime, dt.datetime.isoformat, dt.datetime.fromisoformat),
    ("date", dt.date, dt.date.isoformat, dt.date.fromisoformat),
    ("time", dt.time, dt.time.isoformat, dt.time.fromisoformat),
    ("decimal", Decimal, str, Decimal),
    ("uuid", uuid.UUID, str, uuid.UUID),
    ("bytes", bytes, bytes.hex, bytes.fromhex),
]


def encode_key(values: Sequence[Any]) -> list[Any]:
    """Encode a primary-key tuple for JSON without losing its types."""
    out: list[Any] = []
    for v in values:
        if v is None or isinstance(v, bool | int | float | str):
            out.append(v)
            continue
        if isinstance(v, memoryview | bytearray):
            v = bytes(v)
        for tag, typ, dump, _ in _KEY_TYPES:  # datetime precedes date: it is a subclass
            if isinstance(v, typ):
                out.append({"$t": tag, "v": dump(v)})
                break
        else:
            raise RelVectorError(
                f"primary-key values of type {type(v).__name__} cannot be checkpointed; "
                "supported: int, float, str, bool, date, datetime, time, Decimal, UUID, bytes"
            )
    return out


def decode_key(values: Sequence[Any]) -> list[Any]:
    loads = {tag: load for tag, _, _, load in _KEY_TYPES}
    return [loads[v["$t"]](v["v"]) if isinstance(v, dict) else v for v in values]


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class LocalVectorStore:
    """SQLite-backed :class:`VectorStore` (the ``vector_store="local"`` backend)."""

    def __init__(self, path: str | Path, *, search_chunk_size: int = 1024) -> None:
        if search_chunk_size < 1:
            raise ValueError("search_chunk_size must be >= 1")
        self.path = Path(path)
        self.search_chunk_size = search_chunk_size
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(rv_checkpoints)")}
        for col in ("fingerprint", "owner"):  # added after the first 0.1.0.dev0 index files
            if col not in cols:
                self._conn.execute(
                    f"ALTER TABLE rv_checkpoints ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        self._conn.execute("INSERT OR IGNORE INTO rv_meta VALUES ('format_version', ?)",
                           (_FORMAT_VERSION,))
        self._conn.commit()
        fmt = self._meta("format_version")
        if fmt != _FORMAT_VERSION:
            raise IndexMismatchError(f"{self.path} uses index format {fmt}, expected "
                                     f"{_FORMAT_VERSION}")
        self._dimension = int(self._meta("dimension") or 0)

    def _meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM rv_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def ensure_compatible(self, model_id: str, dimension: int) -> None:
        stored_model, stored_dim = self._meta("model_id"), self._meta("dimension")
        if stored_model is None:
            with self._conn:
                self._conn.execute("INSERT INTO rv_meta VALUES ('model_id', ?)", (model_id,))
                self._conn.execute("INSERT INTO rv_meta VALUES ('dimension', ?)",
                                   (str(dimension),))
            self._dimension = dimension
            return
        if stored_model != model_id or int(stored_dim or 0) != dimension:
            raise IndexMismatchError(
                f"{self.path} was built with {stored_model} ({stored_dim} dims) but the provider "
                f"is {model_id} ({dimension} dims); use a new index path to change models"
            )

    @property
    def model_id(self) -> str | None:
        return self._meta("model_id")

    def content_hashes(self, vector_ids: Sequence[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        ids = list(vector_ids)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            out.update(self._conn.execute(
                f"SELECT vector_id, content_hash FROM rv_records WHERE vector_id IN ({marks})",  # noqa: S608
                chunk,
            ).fetchall())
        return out

    def write_batch(
        self,
        records: Sequence[SemanticRecord],
        vectors: Vectors,
        unchanged_ids: Sequence[str],
        checkpoint: Checkpoint,
    ) -> None:
        """Upsert changed records, mark unchanged ones as seen, advance the checkpoint — atomically.

        Raises :class:`RunSupersededError` (writing nothing) if the writer no longer owns the
        entity's checkpoint because a newer run started or another process resumed this run.
        """
        run_id = checkpoint.run_id
        if len(records) != len(vectors):
            raise RelVectorError("records and vectors differ in length")
        if len(records) and vectors.shape[1] != self._dimension:
            raise IndexMismatchError(f"vector dimension {vectors.shape[1]} != {self._dimension}")
        vecs = normalize(vectors).astype("<f4") if len(records) else vectors
        now = _now()
        with self._conn:
            self._claim(checkpoint, "running")
            self._conn.executemany(
                "INSERT INTO rv_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(vector_id) DO UPDATE SET entity=excluded.entity, "
                "source_table=excluded.source_table, source_pk=excluded.source_pk, "
                "text=excluded.text, metadata=excluded.metadata, refs=excluded.refs, "
                "truncated=excluded.truncated, mapping_version=excluded.mapping_version, "
                "content_hash=excluded.content_hash, vector=excluded.vector, "
                "run_id=excluded.run_id, updated_at=excluded.updated_at",
                [
                    (r.vector_id, r.entity, r.source_table, _dumps(r.source_pk), r.text,
                     _dumps(r.metadata), _dumps(r.references), _dumps(r.truncated),
                     r.mapping_version, r.content_hash, v.tobytes(), run_id, now)
                    for r, v in zip(records, vecs, strict=True)
                ],
            )
            self._conn.executemany("UPDATE rv_records SET run_id = ? WHERE vector_id = ?",
                                   [(run_id, i) for i in unchanged_ids])

    def _claim(self, cp: Checkpoint, status: str) -> None:
        """Compare-and-set: advance the checkpoint only if ``cp.owner`` still holds it."""
        key = None if cp.last_key is None else _dumps(encode_key(cp.last_key))
        cur = self._conn.execute(
            "UPDATE rv_checkpoints SET last_key = ?, processed = ?, status = ?, updated_at = ? "
            "WHERE entity = ? AND run_id = ? AND owner = ? AND status = 'running'",
            (key, cp.processed, status, _now(), cp.entity, cp.run_id, cp.owner),
        )
        if cur.rowcount != 1:
            raise RunSupersededError(
                f"indexing run {cp.run_id} for {cp.entity!r} no longer owns the checkpoint (a "
                "newer run started, another process resumed it, or it already finished); "
                "stopped without writing or pruning"
            )

    def start_run(self, checkpoint: Checkpoint) -> None:
        """Begin a run, taking over the entity's checkpoint from any earlier run or writer."""
        cp = checkpoint
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO rv_checkpoints VALUES (?,?,?,?,?,?,?,?)",
                (cp.entity, cp.run_id, None, "running", cp.processed, _now(), cp.fingerprint,
                 cp.owner),
            )

    def resume_run(self, checkpoint: Checkpoint) -> None:
        """Take over writing for an unfinished run as ``checkpoint.owner``.

        Single writer: whichever process resumed last owns the run; an earlier writer of the
        same run fails with :class:`RunSupersededError` at its next batch and never prunes.
        """
        cp = checkpoint
        with self._conn:
            cur = self._conn.execute(
                "UPDATE rv_checkpoints SET owner = ?, updated_at = ? "
                "WHERE entity = ? AND run_id = ? AND status = 'running'",
                (cp.owner, _now(), cp.entity, cp.run_id),
            )
        if cur.rowcount != 1:
            raise RunSupersededError(f"run {cp.run_id} for {cp.entity!r} is no longer resumable")

    def finish_run(self, checkpoint: Checkpoint, *, prune: bool) -> int:
        """Mark the run completed and, if ``prune``, delete records it did not see — atomically.

        Only the writer that still owns the checkpoint can finish, so an interrupted or
        superseded run never prunes. Returns the number of deleted records.
        """
        cp = checkpoint
        with self._conn:
            self._claim(Checkpoint(cp.entity, cp.run_id, None, "running", cp.processed,
                                   cp.fingerprint, cp.owner), "completed")
            deleted = 0
            if prune:
                deleted = self._conn.execute(
                    "DELETE FROM rv_records WHERE entity = ? AND run_id != ?",
                    (cp.entity, cp.run_id)).rowcount
        return deleted

    def checkpoint(self, entity: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT entity, run_id, last_key, status, processed, fingerprint, owner "
            "FROM rv_checkpoints WHERE entity = ?", (entity,)).fetchone()
        if row is None:
            return None
        key = None if row[2] is None else decode_key(json.loads(row[2]))
        return Checkpoint(row[0], row[1], key, row[3], row[4], row[5], row[6])

    def count(self, entity: str | None = None) -> int:
        if entity is None:
            return int(self._conn.execute("SELECT COUNT(*) FROM rv_records").fetchone()[0])
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM rv_records WHERE entity = ?", (entity,)).fetchone()[0])

    def _where(self, entity: str | None, filters: Mapping[str, Any] | None
               ) -> tuple[str, list[Any]]:
        clauses, params = [], []
        if entity is not None:
            clauses.append("entity = ?")
            params.append(entity)
        for key, value in (filters or {}).items():
            if '"' in key or "\\" in key:
                raise RelVectorError(f"invalid metadata filter key {key!r}")
            clauses.append("json_extract(metadata, ?) IS ?")
            params.extend([f'$."{key}"', value])
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def search(self, vector: Vectors, top_k: int, *, entity: str | None = None,
               filters: Mapping[str, Any] | None = None) -> list[SearchResult]:
        """Exact cosine top-k, streamed: memory is bounded by ``search_chunk_size`` and ``top_k``.

        Rows are read from a single SQLite cursor ``search_chunk_size`` at a time and decoded
        into one reused buffer, so the full vector collection is never held in memory. Entity
        and metadata filters run in SQL, so the vectors of non-matching rows are never decoded.
        Ties are broken by ``vector_id`` ascending, which keeps results independent of chunk
        size and row order.
        """
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if not self._dimension:
            return []
        query = normalize(np.asarray(vector, dtype=np.float32).reshape(1, -1))[0]
        if query.shape[0] != self._dimension:
            raise IndexMismatchError(f"query dimension {query.shape[0]} != {self._dimension}")
        return self._fetch(self._top_k(query.astype(np.float64), top_k, entity, filters))

    def _top_k(self, query: NDArray[np.float64], top_k: int, entity: str | None,
               filters: Mapping[str, Any] | None) -> list[tuple[str, float]]:
        where, params = self._where(entity, filters)
        # No ORDER BY: the scan streams in storage order (no sort buffer holding every row);
        # determinism comes from the explicit (score desc, vector_id asc) ranking below.
        cur = self._conn.execute(
            f"SELECT vector_id, vector FROM rv_records{where}", params)  # noqa: S608
        dim, chunk = self._dimension, self.search_chunk_size
        width = dim * 4
        buf = np.empty((chunk, dim), dtype="<f4")  # decoded vectors, reused for every chunk
        prod = np.empty((chunk, dim), dtype=np.float64)  # products, reused for every chunk
        best: list[tuple[float, str]] = []  # (-score, vector_id), at most top_k entries
        while rows := cur.fetchmany(chunk):
            n = len(rows)
            for i, (_, blob) in enumerate(rows):
                if len(blob) != width:
                    raise IndexMismatchError(f"stored vector {rows[i][0]!r} has {len(blob)} "
                                             f"bytes, expected {width}")
                buf[i] = np.frombuffer(blob, dtype="<f4")
            # Row-wise float64 sums do not depend on how many rows are in the chunk, so a
            # vector's score (and hence tie-breaking) is identical for every chunk size.
            np.multiply(buf[:n], query, out=prod[:n])
            scores = prod[:n].sum(axis=1)
            # Prune before building Python tuples. ">=" keeps ties so vector_id can break them.
            floor = -np.inf
            if n > top_k:  # a row below the chunk's k-th best can never reach the top k
                floor = np.partition(scores, n - top_k)[n - top_k]
            if len(best) == top_k:
                floor = max(floor, -best[-1][0])
            keep = np.flatnonzero(scores >= floor)
            if keep.size:
                best = heapq.nsmallest(
                    top_k, [*best, *((-float(scores[i]), rows[i][0]) for i in keep)])
        return [(vid, -neg) for neg, vid in best]

    def _fetch(self, hits: Iterable[tuple[str, float]]) -> list[SearchResult]:
        out = []
        for vid, score in hits:
            r = self._conn.execute(
                "SELECT text, entity, source_table, source_pk, metadata, refs, truncated "
                "FROM rv_records WHERE vector_id = ?", (vid,)).fetchone()
            out.append(SearchResult(
                vector_id=vid, score=score, text=r[0], entity=r[1], source_table=r[2],
                source_pk=json.loads(r[3]), metadata=json.loads(r[4]),
                references=json.loads(r[5]), truncated=json.loads(r[6]),
            ))
        return out

    def close(self) -> None:
        self._conn.close()
