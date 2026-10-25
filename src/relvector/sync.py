"""Opt-in incremental sync driven by change-tracking columns (no triggers, no CDC, no WAL).

Configure a column per mapped table that the application reliably bumps on every insert and
update (``EntityMapping.change_tracking``, e.g. ``{"orders": "updated_at", "shipments":
"updated_at"}``), run a full :meth:`RelVector.index` once, then call :meth:`RelVector.sync`.

How a sync works:

* For every mapped table (root first, then included tables) it reads ``MAX(tracking)`` as the
  high-water mark, then scans rows with ``watermark - lookback <= tracking <= high-water`` in
  ``(tracking, primary key)`` keyset order, ``batch_size`` rows at a time.
* Each batch of changed rows is mapped to the root rows whose documents it affects:
  a changed root row itself; for a one-to-many child, its current parent (from the source) and
  its previous parent (from the index's own provenance, ``VectorStore.referencing``), so a
  reassigned child updates both documents; for a many-to-one parent, every root row that
  currently references it (keyset-paginated, so memory stays bounded).
* Affected roots are rebuilt from the current source rows with the same deterministic
  ``build_record`` as a full index; only records whose content hash changed are re-embedded.
  A root row that no longer exists (or is soft-deleted) has its record deleted.
* The table's watermark advances only in the same store call that commits the batch's index
  changes, so an interrupted sync never records progress it did not commit. Re-running is
  idempotent: re-processed rows hash the same and are not re-embedded.

Guarantees and limits (read before relying on it):

* Changes are found only through the tracking columns. A change whose tracking value is
  earlier than ``watermark - lookback`` when the sync runs (a transaction that committed
  later than ``lookback`` after taking its timestamp, clock skew between writers, a backfill
  with old timestamps, or an application path that does not bump the column) is NOT seen;
  run :meth:`RelVector.index` to reconcile. Rows whose tracking value is NULL are never seen.
* Equal timestamps are safe: scans use ``>=`` and re-read the ``lookback`` window.
* Hard deletes are not visible to timestamps. A hard-deleted root row keeps its record until
  a full ``index()`` (which prunes) or until it is rebuilt for another reason. A hard-deleted
  child disappears from its parent's document only when that parent is rebuilt (another
  change, or a full ``index()``). Use a root ``soft_delete`` column (and bump the tracking
  column when setting it) to have sync delete records.
* A many-to-one parent row whose primary key changes, or that is hard-deleted, is not
  propagated; neither is a change to a root row's foreign key unless the root's tracking
  column is bumped (it normally is).
* Text tracking columns (SQLite) must use one ISO-8601 format that sorts chronologically.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np

from relvector.embeddings import EmbeddingProvider
from relvector.errors import MappingError, RelVectorError
from relvector.extraction import Extractor, Row
from relvector.indexing import SYNC_FORMAT, tracking_signature
from relvector.mapping import Relation, build_record, jsonable, record_id
from relvector.store import Checkpoint, VectorStore

Lookback = dt.timedelta | int | float | Decimal | None

DEFAULT_LOOKBACK = dt.timedelta(minutes=5)
"""Overlap re-scanned below each watermark for time-based tracking columns."""


class SyncUnavailableError(RelVectorError):
    """Incremental sync cannot run safely; a full ``index()`` is needed first."""


@dataclass
class SyncStats:
    run_id: str
    mode: str = "sync"  # "full" when sync(full_fallback=True) ran a full index() instead
    changed_rows: dict[str, int] = field(default_factory=dict)
    roots_rebuilt: int = 0
    embedded: int = 0
    unchanged: int = 0
    deleted: int = 0
    batches: int = 0
    truncated_records: int = 0
    watermarks: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None  # why a full index ran instead (mode == "full")
    timings: dict[str, float] = field(
        default_factory=lambda: {"extract": 0.0, "embed": 0.0, "store": 0.0})

    @property
    def rows(self) -> int:
        return sum(self.changed_rows.values())

    def __str__(self) -> str:
        t = ", ".join(f"{k} {v:.2f}s" for k, v in self.timings.items())
        seen = ", ".join(f"{k} {v}" for k, v in self.changed_rows.items()) or "none"
        return (f"{self.mode}: changed rows ({seen}); {self.roots_rebuilt} roots rebuilt, "
                f"{self.embedded} embedded, {self.unchanged} unchanged, {self.deleted} "
                f"deleted ({t})")


def _lower_bound(watermark: Any, lookback: Lookback) -> Any:
    """``watermark - lookback`` in the watermark's own type (``None`` = no lower bound)."""
    if watermark is None:
        return None
    if isinstance(watermark, bool):
        raise RelVectorError("a boolean column cannot be used for change tracking")
    temporal = isinstance(watermark, dt.date) or (
        isinstance(watermark, str) and _parse_iso(watermark) is not None)
    if lookback is None:
        lookback = DEFAULT_LOOKBACK if temporal else 0
    if isinstance(watermark, dt.date):
        if not isinstance(lookback, dt.timedelta):
            raise RelVectorError("lookback must be a timedelta for date/time tracking columns")
        return watermark - lookback
    if isinstance(watermark, int | float | Decimal):
        if isinstance(lookback, dt.timedelta):
            raise RelVectorError("lookback must be a number for numeric tracking columns "
                                 f"(watermark {watermark!r})")
        step = Decimal(str(lookback)) if isinstance(watermark, Decimal) else lookback
        return watermark - step  # type: ignore[operator]
    if isinstance(watermark, str):
        parsed = _parse_iso(watermark)
        if parsed is None:
            if lookback:
                raise RelVectorError(f"tracking value {watermark!r} is not an ISO-8601 date/time"
                                     "; only lookback=0 is supported for it")
            return watermark
        if not isinstance(lookback, dt.timedelta):
            raise RelVectorError("lookback must be a timedelta for date/time tracking columns")
        if not lookback:
            return watermark
        moved = parsed - lookback
        if isinstance(moved, dt.datetime):
            sep = watermark[10] if len(watermark) > 10 else "T"
            return moved.isoformat(sep=sep)
        return moved.isoformat()
    if lookback:
        raise RelVectorError(f"tracking values of type {type(watermark).__name__} support only "
                             "lookback=0")
    return watermark


def _parse_iso(value: str) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(value) if len(value) > 10 else \
            dt.date.fromisoformat(value)
    except ValueError:
        return None


def _later(a: Any, b: Any) -> Any:
    if a is None:
        return b
    if b is None:
        return a
    try:
        return b if b > a else a
    except TypeError:  # the column's type changed; trust the value just read
        return b


def _retype(value: Any, type_name: str) -> Any:
    """Undo ``jsonable`` for a primary-key value stored as JSON text (non-SQLite sources)."""
    if not isinstance(value, str):
        return value
    t = type_name.upper()
    try:
        if "UUID" in t:
            return uuid.UUID(value)
        if "TIMESTAMP" in t or "DATETIME" in t:
            return dt.datetime.fromisoformat(value)
        if t.startswith("DATE"):
            return dt.date.fromisoformat(value)
        if t.startswith("TIME"):
            return dt.time.fromisoformat(value)
        if "NUMERIC" in t or "DECIMAL" in t:
            return Decimal(value)
    except ValueError:
        return value
    return value


class Syncer:
    """Incremental sync of one configured entity (see the module docstring)."""

    def __init__(self, extractor: Extractor, provider: EmbeddingProvider,
                 store: VectorStore) -> None:
        self.extractor = extractor
        self.provider = provider
        self.store = store
        self.resolved = extractor.resolved

    def unavailable(self) -> RelVectorError | None:
        """Why a sync cannot run safely now (``None`` when it can)."""
        r = self.resolved
        if r.untracked_tables:
            return MappingError(
                f"sync() needs a change-tracking column for every mapped table; missing for "
                f"{', '.join(r.untracked_tables)}. Configure change_tracking={{table: column}} "
                "or run index() for a full reconciliation (sync(full_fallback=True) does that)")
        previous = self.store.checkpoint(r.entity)
        state = dict(previous.state or {}) if previous is not None else {}
        if previous is not None and previous.status == "running" and state.get("mode") != "sync":
            return SyncUnavailableError(
                f"a full index() run for {r.entity!r} is in progress or was interrupted; finish "
                "it (index(resume=True)) before sync()")
        if previous is None or not isinstance(state.get("watermarks"), dict):
            return SyncUnavailableError(
                f"no completed full index with change tracking for {r.entity!r}; run index() "
                "once with change_tracking configured before sync()")
        if state.get("sync_format") != SYNC_FORMAT:
            return SyncUnavailableError("the index's sync state has an unknown format; run "
                                        "index() for a full reconciliation")
        if previous.fingerprint != r.fingerprint:
            return SyncUnavailableError(
                f"the mapping for {r.entity!r} changed since the last index, so every document "
                "may change; run index() for a full re-index")
        signature = tracking_signature(r)
        if {k: state.get(k) for k in signature} != signature:
            return SyncUnavailableError(
                "change_tracking or soft_delete changed since the last index, so the stored "
                "watermarks do not apply; run index() for a full reconciliation")
        return None

    def run(
        self,
        batch_size: int = 500,
        *,
        lookback: Lookback = None,
        progress: Callable[[SyncStats], None] | None = None,
    ) -> SyncStats:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if (lookback < dt.timedelta(0) if isinstance(lookback, dt.timedelta)
                else lookback is not None and lookback < 0):
            raise ValueError("lookback must be >= 0")
        r = self.resolved
        self.store.ensure_compatible(self.provider.model_id, self.provider.dimension)
        problem = self.unavailable()
        if problem is not None:
            raise problem
        previous = self.store.checkpoint(r.entity)
        assert previous is not None and previous.state is not None
        base = {k: v for k, v in previous.state.items()
                if k not in ("watermarks", "pending_watermarks")}
        base.update(mode="sync", sync_format=SYNC_FORMAT, **tracking_signature(r))
        watermarks: dict[str, Any] = dict(previous.state["watermarks"])
        stats = SyncStats(run_id=uuid.uuid4().hex, changed_rows=dict.fromkeys(r.tables, 0))
        owner = uuid.uuid4().hex

        def checkpoint(state: Mapping[str, Any] | None) -> Checkpoint:
            return Checkpoint(r.entity, stats.run_id, None, "running", stats.rows,
                              r.fingerprint, owner, state)

        self.store.start_run(checkpoint({**base, "watermarks": dict(watermarks)}))
        relations = {rel.table: rel for rel in r.relations}
        for table in r.tables:
            column = r.tracking[table]
            t0 = time.perf_counter()
            high = self.extractor.max_value(table, column)
            stats.timings["extract"] += time.perf_counter() - t0
            if high is None:
                continue
            low = _lower_bound(watermarks.get(table), lookback)
            rel = relations.get(table)
            pk = r.primary_key if rel is None else rel.primary_key
            extra = () if rel is None else (rel.related_column,)
            scan = self.extractor.iter_changed(table, column, pk, extra, low, high, batch_size)
            while True:
                t0 = time.perf_counter()
                rows = next(scan, None)
                stats.timings["extract"] += time.perf_counter() - t0
                if rows is None:
                    break
                stats.changed_rows[table] += len(rows)
                stats.batches += 1
                mark = _later(watermarks.get(table), rows[-1][column])
                state = {**base, "watermarks": {**watermarks, table: mark}}
                self._rebuild(self._affected(rel, rows, batch_size), stats, checkpoint, state)
                watermarks[table] = mark
                if progress is not None:
                    progress(stats)
            watermarks[table] = _later(watermarks.get(table), high)

        t0 = time.perf_counter()
        stats.watermarks = dict(watermarks)
        self.store.finish_run(checkpoint({**base, "watermarks": watermarks}), prune=False)
        stats.timings["store"] += time.perf_counter() - t0
        return stats

    # --- changed rows -> affected root keys ------------------------------------------------

    def _affected(self, rel: Relation | None, rows: list[Row],
                  batch_size: int) -> Iterator[list[tuple[Any, ...]]]:
        """Chunks (at most ``batch_size``) of root primary keys whose documents may change."""
        r = self.resolved
        if rel is None:
            yield [tuple(row[c] for c in r.primary_key) for row in rows]
            return
        keys = [row[rel.related_column] for row in rows]
        if rel.kind == "one_to_many" and r.primary_key == (rel.root_column,):
            current = sorted({k for k in keys if k is not None},
                             key=lambda k: (str(type(k)), k))
            for i in range(0, len(current), batch_size):
                yield [(k,) for k in current[i:i + batch_size]]
        else:
            yield from self.extractor.iter_root_keys(rel.root_column, keys, batch_size)
        if rel.kind == "one_to_many":
            # Previous parents, from the index's provenance: finds reassigned children.
            refs = self.store.referencing(
                r.entity, rel.table,
                [{c: jsonable(row[c]) for c in rel.primary_key} for row in rows])
            retype = self.extractor.engine.dialect.name != "sqlite"
            previous = [
                tuple(_retype(spk.get(c), t) if retype else spk.get(c)
                      for c, t in zip(r.primary_key, r.primary_key_types or
                                      ("",) * len(r.primary_key), strict=True))
                for spk in refs.values()
            ]
            for i in range(0, len(previous), batch_size):
                yield previous[i:i + batch_size]

    # --- rebuild ---------------------------------------------------------------------------

    def _rebuild(
        self,
        chunks: Iterator[list[tuple[Any, ...]]],
        stats: SyncStats,
        checkpoint: Callable[[Mapping[str, Any] | None], Checkpoint],
        state: Mapping[str, Any],
    ) -> None:
        """Rebuild each chunk of roots; the batch's last store call carries ``state``."""
        r = self.resolved
        seen: set[str] = set()
        t0 = time.perf_counter()
        pending = next(chunks, None)
        stats.timings["extract"] += time.perf_counter() - t0
        if pending is None:  # nothing affected: still record the scanned progress
            t0 = time.perf_counter()
            self.store.write_batch([], self._empty(), [], checkpoint(state))
            stats.timings["store"] += time.perf_counter() - t0
            return
        while pending is not None:
            t0 = time.perf_counter()
            chunk = pending
            pending = next(chunks, None)  # look ahead: is this the batch's last store call?
            ids = {record_id(r, k): k for k in chunk}
            todo = [k for vid, k in ids.items() if vid not in seen]
            seen.update(ids)
            bundles = self.extractor.fetch_roots(todo)
            records = [build_record(r, b.row, b.related) for b in bundles]
            found = {rec.vector_id for rec in records}
            missing = [record_id(r, k) for k in todo if record_id(r, k) not in found]
            known = self.store.content_hashes([rec.vector_id for rec in records])
            changed = [rec for rec in records if known.get(rec.vector_id) != rec.content_hash]
            unchanged = [rec.vector_id for rec in records
                         if known.get(rec.vector_id) == rec.content_hash]
            t1 = time.perf_counter()
            stats.timings["extract"] += t1 - t0
            vectors = (self.provider.embed([rec.text for rec in changed]) if changed
                       else self._empty())
            t2 = time.perf_counter()
            stats.timings["embed"] += t2 - t1
            final = state if pending is None else None
            if missing:
                stats.deleted += self.store.delete_records(missing, checkpoint(None))
            self.store.write_batch(changed, vectors, unchanged, checkpoint(final))
            stats.timings["store"] += time.perf_counter() - t2
            stats.roots_rebuilt += len(records)
            stats.embedded += len(changed)
            stats.unchanged += len(unchanged)
            stats.truncated_records += sum(1 for rec in records if rec.truncated)

    def _empty(self) -> Any:
        return np.zeros((0, self.provider.dimension), dtype=np.float32)
