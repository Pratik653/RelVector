"""Optional FAISS approximate-nearest-neighbour (ANN) backend over the local SQLite store.

:class:`FaissVectorStore` is a :class:`~relvector.store.LocalVectorStore` that keeps a derived
FAISS index next to the SQLite index file. SQLite stays the single source of truth for records,
vectors and checkpoints; the FAISS files are an acceleration structure that can always be
rebuilt from it (:meth:`FaissVectorStore.rebuild`).

Files, for an index at ``<path>``:

* ``<path>.faiss`` - the FAISS index (written with ``faiss.write_index``; never pickled).
* ``<path>.faiss.json`` - sidecar: model id, dimension, vector count and a checksum of every
  stored (rowid, vector) pair, taken when the FAISS file was written.
* ``<path>.faiss.dirty`` - present while the in-memory index holds changes not yet saved.

**Index family.** One ``IndexIVFFlat`` with inner product on L2-normalised vectors (cosine),
keyed by the SQLite ``rowid`` of each record (stable across upserts; a delete + reinsert gets a
new one), with a hashtable direct map so ``remove_ids`` is cheap. IVF supports real deletes and
in-place updates (remove + add the same id), unlike HNSW, which needs tombstones. Its coarse
quantizer is trained on a sample when the index is built; once the index has grown more than
``retrain_growth`` times beyond the size it was trained on, it is rebuilt (retrained) before the
next ANN search.

**When ANN is used.** Only when it can answer the query completely; otherwise the exact
streaming search of :class:`LocalVectorStore` runs. Exact search is used when

* ``filters`` are given (an ANN candidate set cannot guarantee complete filtered results),
* ``entity`` is given and the index holds other entities as well (same reason),
* the index holds fewer than ``ann_min_vectors`` vectors (exact is fast enough there).

No FAISS index exists below ``ann_min_vectors``; it is built from SQLite once the store reaches
that size, at the end of an indexing run (:meth:`finish_run`) or at the next search.

``last_search_mode`` (``"ann"`` or ``"exact"``) and ``last_search_reason`` record what the last
:meth:`search` did. ANN results are never presented as exact: FAISS only proposes
``top_k * oversample`` candidates, which are then re-scored exactly like the parent (float64
row-wise dot products of the stored float32 vectors, ties broken by ``vector_id`` ascending), so
every returned ``score`` is the exact cosine similarity and ordering semantics match; only
recall is approximate (a true neighbour can be missed if FAISS does not propose it).

**Consistency and crash safety.** Mutations write the dirty marker *before* the SQLite commit,
apply the change to the in-memory FAISS index in the post-commit hook, and save the FAISS file
atomically (temp file + ``os.replace``) on :meth:`flush`, :meth:`close` and at the end of every
:meth:`finish_run`, then clear the marker. On open, the FAISS file is rebuilt from SQLite
(streamed in chunks) if it is missing, the dirty marker is present, it cannot be read, or it
disagrees with SQLite (model id, dimension, count or checksum); ``last_rebuild_reason`` says
why. If another connection changes the SQLite file while this store is open (detected with
``PRAGMA data_version``), the FAISS index is rebuilt before the next ANN search. Use one
writer process per index; readers in other processes stay correct but rebuild after writes.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from relvector.embeddings import Vectors, normalize
from relvector.errors import IndexMismatchError, RelVectorError
from relvector.mapping import SemanticRecord
from relvector.store import Checkpoint, LocalVectorStore, SearchResult

log = logging.getLogger(__name__)

_SIDECAR_FORMAT = 1
_SQL_CHUNK = 500  # bound-parameter chunk for IN (...) queries


def _import_faiss() -> Any:
    """Import faiss lazily so ``import relvector`` never needs it."""
    try:
        return importlib.import_module("faiss")
    except ImportError as exc:
        raise RelVectorError(
            "the FAISS vector store needs faiss-cpu; install it with: "
            "pip install 'relvector[faiss]'"
        ) from exc


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class FaissVectorStore(LocalVectorStore):
    """SQLite-backed :class:`~relvector.store.VectorStore` with a derived FAISS ANN index.

    Args:
        path: the SQLite index file (the FAISS files live next to it).
        search_chunk_size: chunk size of the exact streaming search (see the parent).
        ann_min_vectors: below this many vectors, search exactly and build no FAISS index.
        oversample: FAISS proposes ``top_k * oversample`` candidates for exact re-ranking.
        nprobe: IVF lists probed per query (default: a quarter of the lists, at least 8).
        nlist: IVF lists (default: ``4 * sqrt(n)``, capped so each list gets ~39 training
            points).
        retrain_growth: rebuild (retrain) once the index holds this many times the vectors it
            was trained on.
        build_chunk_size: rows read from SQLite at a time while (re)building.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        search_chunk_size: int = 1024,
        ann_min_vectors: int = 5000,
        oversample: int = 4,
        nprobe: int | None = None,
        nlist: int | None = None,
        retrain_growth: float = 4.0,
        build_chunk_size: int = 4096,
    ) -> None:
        self._faiss = _import_faiss()
        if ann_min_vectors < 0:
            raise ValueError("ann_min_vectors must be >= 0")
        if oversample < 1:
            raise ValueError("oversample must be >= 1")
        if nprobe is not None and nprobe < 1:
            raise ValueError("nprobe must be >= 1")
        if nlist is not None and nlist < 1:
            raise ValueError("nlist must be >= 1")
        if retrain_growth <= 1:
            raise ValueError("retrain_growth must be > 1")
        if build_chunk_size < 1:
            raise ValueError("build_chunk_size must be >= 1")
        self.ann_min_vectors = ann_min_vectors
        self.oversample = oversample
        self.nprobe = nprobe
        self.nlist = nlist
        self.retrain_growth = retrain_growth
        self.build_chunk_size = build_chunk_size
        self._index: Any = None
        self._trained_on = 0
        self._dirty = False  # in-memory index has unsaved changes (the marker file exists)
        self._stale: str | None = None  # reason the in-memory index must be rebuilt
        self._pending: list[int] = []  # rowids about to be deleted by the current mutation
        self.last_search_mode: str | None = None
        self.last_search_reason = ""
        self.last_rebuild_reason: str | None = None
        super().__init__(path, search_chunk_size=search_chunk_size)
        self.index_path = Path(f"{self.path}.faiss")
        self.meta_path = Path(f"{self.path}.faiss.json")
        self.dirty_path = Path(f"{self.path}.faiss.dirty")
        self._data_version = self._read_data_version()
        self._open_index()

    # -- opening, validating, rebuilding -------------------------------------------------

    def _read_data_version(self) -> int:
        return int(self._conn.execute("PRAGMA data_version").fetchone()[0])

    def _open_index(self) -> None:
        problem = self._load()
        if problem is None:
            return
        self._remove_files()
        if self.count() >= max(1, self.ann_min_vectors):
            self.rebuild(reason=problem)
        elif problem != "no FAISS index file":
            log.info("discarded FAISS index for %s (%s); it is rebuilt when needed",
                     self.path, problem)

    def _load(self) -> str | None:
        """Load the FAISS file if it is consistent with SQLite; else return why not."""
        if not self.index_path.exists():
            return "no FAISS index file"
        if self.dirty_path.exists():
            return "dirty marker present (unclean shutdown during a mutation)"
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            index = self._faiss.read_index(str(self.index_path))
        except (OSError, ValueError, RuntimeError) as exc:
            return f"unreadable FAISS index or sidecar: {exc}"
        if not isinstance(meta, dict) or meta.get("format") != _SIDECAR_FORMAT:
            return "unknown FAISS sidecar format"
        if meta.get("model_id") != self.model_id or meta.get("dimension") != self._dimension:
            return (f"model mismatch: FAISS index is {meta.get('model_id')} "
                    f"({meta.get('dimension')} dims), SQLite is {self.model_id} "
                    f"({self._dimension} dims)")
        if index.d != self._dimension or index.ntotal != meta.get("count"):
            return "FAISS index does not match its sidecar"
        if index.ntotal != self.count() or meta.get("checksum") != self._checksum():
            return "FAISS index is out of sync with SQLite (count or checksum differ)"
        self._index = index
        self._trained_on = int(meta.get("trained_on", index.ntotal))
        return None

    def _checksum(self) -> str:
        """Checksum of every stored (rowid, vector), streamed in rowid order."""
        h = hashlib.sha256()
        cur = self._conn.execute("SELECT rowid, vector FROM rv_records ORDER BY rowid")
        while rows := cur.fetchmany(self.build_chunk_size):
            for rowid, blob in rows:
                h.update(rowid.to_bytes(8, "little", signed=True))
                h.update(blob)
        return h.hexdigest()

    def _remove_files(self) -> None:
        for p in (self.index_path, self.meta_path, self.dirty_path):
            p.unlink(missing_ok=True)
        self._dirty = False

    def _auto_nlist(self, n: int) -> int:
        if self.nlist is not None:
            return max(1, min(self.nlist, n))
        return max(1, min(int(4 * math.sqrt(n)), n // 39))

    def _nprobe(self) -> int:
        nlist = int(self._index.nlist)
        if self.nprobe is not None:
            return min(self.nprobe, nlist)
        return min(nlist, max(8, math.ceil(nlist / 4)))

    def rebuild(self, reason: str = "explicit rebuild") -> None:
        """Rebuild the FAISS index from SQLite (two streamed passes) and save it atomically."""
        faiss = self._faiss
        self._index, self._stale, self._trained_on = None, None, 0
        self._remove_files()
        self._data_version = self._read_data_version()
        dim = self._dimension
        n = self.count()
        if not dim or not n:
            self.last_rebuild_reason = reason
            return
        width = dim * 4
        self._conn.execute("BEGIN")  # one read snapshot for both passes
        try:
            n = self.count()
            nlist = self._auto_nlist(n)
            sample_size = min(n, max(64 * nlist, 1000), 100_000)
            step = max(1, n // sample_size)
            sample = np.empty((sample_size, dim), dtype="<f4")
            taken, seen = 0, 0
            cur = self._conn.execute("SELECT vector FROM rv_records ORDER BY rowid")
            while rows := cur.fetchmany(self.build_chunk_size):
                for (blob,) in rows:
                    if seen % step == 0 and taken < sample_size:
                        if len(blob) != width:
                            raise IndexMismatchError(f"stored vector has {len(blob)} bytes, "
                                                     f"expected {width}")
                        sample[taken] = np.frombuffer(blob, dtype="<f4")
                        taken += 1
                    seen += 1
            quantizer = faiss.IndexFlatIP(dim)
            index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
            index.train(np.ascontiguousarray(sample[:taken], dtype=np.float32))
            index.set_direct_map_type(faiss.DirectMap.Hashtable)
            h = hashlib.sha256()
            buf = np.empty((self.build_chunk_size, dim), dtype="<f4")
            ids = np.empty(self.build_chunk_size, dtype=np.int64)
            cur = self._conn.execute("SELECT rowid, vector FROM rv_records ORDER BY rowid")
            while rows := cur.fetchmany(self.build_chunk_size):
                for i, (rowid, blob) in enumerate(rows):
                    if len(blob) != width:
                        raise IndexMismatchError(f"stored vector has {len(blob)} bytes, "
                                                 f"expected {width}")
                    buf[i] = np.frombuffer(blob, dtype="<f4")
                    ids[i] = rowid
                    h.update(rowid.to_bytes(8, "little", signed=True))
                    h.update(blob)
                k = len(rows)
                index.add_with_ids(np.ascontiguousarray(buf[:k], dtype=np.float32), ids[:k])
            checksum = h.hexdigest()
        finally:
            self._conn.commit()
        self._index = index
        self._trained_on = int(index.ntotal)
        self._save_files(checksum)
        self.last_rebuild_reason = reason
        log.info("rebuilt FAISS index for %s from SQLite (%d vectors, nlist=%d): %s",
                 self.path, index.ntotal, nlist, reason)

    def _save_files(self, checksum: str | None = None) -> None:
        index = self._index
        meta = {
            "format": _SIDECAR_FORMAT,
            "model_id": self.model_id,
            "dimension": self._dimension,
            "count": int(index.ntotal),
            "checksum": checksum if checksum is not None else self._checksum(),
            "trained_on": self._trained_on,
            "nlist": int(index.nlist),
            "metric": "inner_product",
        }
        tmp = self.index_path.with_name(self.index_path.name + ".tmp")
        self._faiss.write_index(index, str(tmp))
        os.replace(tmp, self.index_path)
        _write_atomic(self.meta_path, json.dumps(meta, sort_keys=True).encode())
        self.dirty_path.unlink(missing_ok=True)
        self._dirty = False

    def flush(self) -> None:
        """Save pending FAISS changes to disk (also done by ``close`` and ``finish_run``)."""
        if self._index is None or not self._dirty:
            return
        if self._stale is not None or self._read_data_version() != self._data_version:
            self.rebuild(reason=self._stale or "SQLite changed by another connection")
            return
        self._save_files()

    def close(self) -> None:
        try:
            self.flush()
        except Exception:  # SQLite is the truth; the marker left behind forces a rebuild
            log.warning("could not save FAISS index for %s", self.path, exc_info=True)
        super().close()

    # -- mutations ---------------------------------------------------------------------------

    def _mark_dirty(self) -> None:
        if self._index is None or self._dirty:
            return
        _write_atomic(self.dirty_path, b"unsaved FAISS changes; rebuilt from SQLite on open\n")
        self._dirty = True

    def _rowids(self, sql: str, params: Sequence[Any]) -> list[int]:
        return [int(r[0]) for r in self._conn.execute(sql, params)]

    def _rowids_of(self, vector_ids: Sequence[str]) -> list[int]:
        ids = list(dict.fromkeys(vector_ids))
        out: list[int] = []
        for i in range(0, len(ids), _SQL_CHUNK):
            chunk = ids[i:i + _SQL_CHUNK]
            out += self._rowids(
                f"SELECT rowid FROM rv_records WHERE vector_id IN ({','.join('?' * len(chunk))})",  # noqa: S608
                chunk)
        return out

    def write_batch(self, records: Sequence[SemanticRecord], vectors: Vectors,
                    unchanged_ids: Sequence[str], checkpoint: Checkpoint) -> None:
        if len(records):
            self._mark_dirty()
        super().write_batch(records, vectors, unchanged_ids, checkpoint)

    def delete_records(self, vector_ids: Sequence[str], checkpoint: Checkpoint) -> int:
        if self._index is not None:
            self._mark_dirty()
            self._pending = self._rowids_of(vector_ids)
        try:
            return super().delete_records(vector_ids, checkpoint)
        finally:
            self._pending = []

    def finish_run(self, checkpoint: Checkpoint, *, prune: bool) -> int:
        if prune and self._index is not None:
            self._mark_dirty()
            self._pending = self._rowids(
                "SELECT rowid FROM rv_records WHERE entity = ? AND run_id != ?",
                (checkpoint.entity, checkpoint.run_id))
        try:
            deleted = super().finish_run(checkpoint, prune=prune)
        finally:
            self._pending = []
        if self._index is None and self.count() >= max(1, self.ann_min_vectors):
            self.rebuild(reason=f"index reached ann_min_vectors={self.ann_min_vectors}")
        else:
            self.flush()
        return deleted

    def _after_commit(self, upserted: Sequence[str], deleted: Sequence[str]) -> None:
        """Apply a committed SQLite mutation to the in-memory FAISS index."""
        index = self._index
        if index is None or self._stale is not None:
            return
        try:
            if deleted and self._pending:
                index.remove_ids(np.asarray(self._pending, dtype=np.int64))
            ids_all = list(dict.fromkeys(upserted))
            for i in range(0, len(ids_all), _SQL_CHUNK):
                chunk = ids_all[i:i + _SQL_CHUNK]
                rows = self._conn.execute(
                    "SELECT rowid, vector FROM rv_records "  # noqa: S608
                    f"WHERE vector_id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
                if not rows:
                    continue
                ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
                vecs = np.frombuffer(b"".join(r[1] for r in rows), dtype="<f4")
                index.remove_ids(ids)  # an updated record keeps its rowid: replace its vector
                index.add_with_ids(
                    np.ascontiguousarray(vecs.reshape(len(rows), -1), dtype=np.float32), ids)
            if index.ntotal > self.retrain_growth * max(1, self._trained_on):
                self._stale = (f"index grew from {self._trained_on} to {index.ntotal} vectors "
                               "since training; retraining")
        except Exception as exc:  # the SQLite commit stands; recover by rebuilding from it
            log.warning("FAISS update failed for %s; it will be rebuilt", self.path,
                        exc_info=True)
            self._stale = f"FAISS update failed: {exc}"

    # -- search ------------------------------------------------------------------------------

    def _exact_reason(self, entity: str | None, filters: Mapping[str, Any] | None) -> str | None:
        """Why this query must run exactly, or ``None`` if ANN can answer it completely."""
        if filters:
            return "metadata filters given: exact search (ANN candidates are not filter-complete)"
        if entity is not None:
            lo, hi = self._conn.execute(
                "SELECT (SELECT MIN(entity) FROM rv_records), "
                "(SELECT MAX(entity) FROM rv_records)").fetchone()
            if lo != hi or lo != entity:
                return "entity filter on an index holding other entities: exact search"
        if self._index is not None and self._read_data_version() != self._data_version:
            self.rebuild(reason="SQLite changed by another connection")
        elif self._stale is not None:
            self.rebuild(reason=self._stale)
        elif self._index is None and self.count() >= max(1, self.ann_min_vectors):
            self.rebuild(reason=f"index reached ann_min_vectors={self.ann_min_vectors}")
        n = 0 if self._index is None else int(self._index.ntotal)
        if self._index is None or n < self.ann_min_vectors:
            return f"{self.count()} vectors < ann_min_vectors={self.ann_min_vectors}: exact search"
        return None

    def search(self, vector: Vectors, top_k: int, *, entity: str | None = None,
               filters: Mapping[str, Any] | None = None) -> list[SearchResult]:
        """Top-k by cosine: ANN candidates re-scored exactly, or exact search (see module doc)."""
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if not self._dimension:
            self.last_search_mode, self.last_search_reason = "exact", "empty index"
            return []
        query = normalize(np.asarray(vector, dtype=np.float32).reshape(1, -1))[0]
        if query.shape[0] != self._dimension:
            raise IndexMismatchError(f"query dimension {query.shape[0]} != {self._dimension}")
        reason = self._exact_reason(entity, filters)
        if reason is not None:
            self.last_search_mode, self.last_search_reason = "exact", reason
            return super().search(vector, top_k, entity=entity, filters=filters)
        hits = self._ann_top_k(query, top_k)
        self.last_search_mode = "ann"
        self.last_search_reason = (
            f"FAISS IVF (nprobe={self._nprobe()}/{self._index.nlist}) proposed "
            f"{top_k * self.oversample} candidates, re-scored exactly; recall is approximate")
        return self._fetch(hits)

    def _ann_top_k(self, query: NDArray[np.float32], top_k: int) -> list[tuple[str, float]]:
        index = self._index
        index.nprobe = self._nprobe()
        k = min(int(index.ntotal), top_k * self.oversample)
        _, labels = index.search(np.ascontiguousarray(query.reshape(1, -1)), k)
        cand = [int(i) for i in labels[0] if i >= 0]
        rows: list[tuple[str, bytes]] = []
        for i in range(0, len(cand), _SQL_CHUNK):
            chunk = cand[i:i + _SQL_CHUNK]
            rows += self._conn.execute(
                "SELECT vector_id, vector FROM rv_records "  # noqa: S608
                f"WHERE rowid IN ({','.join('?' * len(chunk))})", chunk).fetchall()
        if not rows:
            return []
        dim = self._dimension
        width = dim * 4
        buf = np.empty((len(rows), dim), dtype="<f4")
        for i, (vid, blob) in enumerate(rows):
            if len(blob) != width:
                raise IndexMismatchError(f"stored vector {vid!r} has {len(blob)} bytes, "
                                         f"expected {width}")
            buf[i] = np.frombuffer(blob, dtype="<f4")
        # Same arithmetic as LocalVectorStore._top_k, so scores equal exact search bit for bit.
        prod = np.empty((len(rows), dim), dtype=np.float64)
        np.multiply(buf, query.astype(np.float64), out=prod)
        scores = prod.sum(axis=1)
        ranked = sorted((-float(s), vid) for s, (vid, _) in zip(scores, rows, strict=True))
        return [(vid, -neg) for neg, vid in ranked[:top_k]]
