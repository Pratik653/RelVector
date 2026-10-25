"""The indexing pipeline: extract a batch -> build records -> embed changed ones -> write.

Recovery model:

* Each batch is written in one store transaction together with its checkpoint, so a crash
  leaves the index at a batch boundary. ``resume=True`` continues an unfinished run from its
  last committed key; re-processing a batch is harmless because writes are upserts keyed by a
  deterministic vector id. Resuming requires the mapping to be unchanged. Checkpoint keys keep
  their types (dates, UUIDs, decimals), so a resumed scan compares them as the column does.
* Starting a run takes over the entity's checkpoint. An older run that is still going (another
  process, or one that was abandoned) fails with ``RunSupersededError`` at its next batch and
  never prunes; the newest run is the one that completes.
* Each ``run()`` call is a writer with its own owner token. Resuming a run takes it over, so
  if two processes resume the same run, the one that resumed first is rejected with
  ``RunSupersededError`` at its next batch. There is never more than one writer that can
  advance the checkpoint or prune.
* Records whose content hash is unchanged are not re-embedded, only marked as seen.
* When a run finishes, records of the entity that the run did not see are deleted (the source
  rows were deleted or no longer map). Interrupted runs never prune.

This is a full re-scan ("manual re-indexing"); it is not change-data-capture.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from relvector.embeddings import EmbeddingProvider
from relvector.errors import RelVectorError
from relvector.extraction import Extractor
from relvector.mapping import build_record
from relvector.store import Checkpoint, VectorStore


@dataclass
class IndexStats:
    run_id: str
    rows: int = 0
    embedded: int = 0
    unchanged: int = 0
    deleted: int = 0
    batches: int = 0
    truncated_records: int = 0
    resumed: bool = False
    timings: dict[str, float] = field(
        default_factory=lambda: {"extract": 0.0, "embed": 0.0, "store": 0.0})

    @property
    def rows_per_second(self) -> float:
        total = sum(self.timings.values())
        return self.rows / total if total else 0.0

    def __str__(self) -> str:
        t = ", ".join(f"{k} {v:.2f}s" for k, v in self.timings.items())
        return (f"{self.rows} rows in {self.batches} batches: {self.embedded} embedded, "
                f"{self.unchanged} unchanged, {self.deleted} deleted ({t}; "
                f"{self.rows_per_second:.0f} rows/s)")


class Indexer:
    def __init__(self, extractor: Extractor, provider: EmbeddingProvider,
                 store: VectorStore) -> None:
        self.extractor = extractor
        self.provider = provider
        self.store = store

    def run(
        self,
        batch_size: int = 500,
        *,
        resume: bool = False,
        prune: bool = True,
        progress: Callable[[IndexStats], None] | None = None,
    ) -> IndexStats:
        resolved = self.extractor.resolved
        entity = resolved.entity
        self.store.ensure_compatible(self.provider.model_id, self.provider.dimension)

        owner = uuid.uuid4().hex
        previous = self.store.checkpoint(entity)
        if resume and previous is not None and previous.status == "running":
            if previous.fingerprint != resolved.fingerprint:
                raise RelVectorError(
                    f"cannot resume run {previous.run_id} for {entity!r}: the mapping changed "
                    "since it started, so resuming would mix old and new documents; run "
                    "index() without resume=True for a full re-index"
                )
            stats = IndexStats(run_id=previous.run_id, rows=previous.processed, resumed=True)
            after = previous.last_key
            self.store.resume_run(Checkpoint(entity, stats.run_id, after, "running",
                                             stats.rows, resolved.fingerprint, owner))
        else:
            stats = IndexStats(run_id=uuid.uuid4().hex)
            after = None
            self.store.start_run(Checkpoint(entity, stats.run_id, None, "running", 0,
                                            resolved.fingerprint, owner))

        batches = self.extractor.iter_batches(batch_size, after)
        while True:
            t0 = time.perf_counter()
            batch = next(batches, None)
            t1 = time.perf_counter()
            stats.timings["extract"] += t1 - t0
            if batch is None:
                break
            records = [build_record(resolved, b.row, b.related) for b in batch.bundles]
            known = self.store.content_hashes([r.vector_id for r in records])
            changed = [r for r in records if known.get(r.vector_id) != r.content_hash]
            unchanged = [r.vector_id for r in records if known.get(r.vector_id) == r.content_hash]
            t2 = time.perf_counter()
            stats.timings["extract"] += t2 - t1  # record building is part of extraction
            vectors = (self.provider.embed([r.text for r in changed]) if changed
                       else np.zeros((0, self.provider.dimension), dtype=np.float32))
            t3 = time.perf_counter()
            stats.timings["embed"] += t3 - t2
            stats.rows += len(records)
            stats.embedded += len(changed)
            stats.unchanged += len(unchanged)
            stats.batches += 1
            stats.truncated_records += sum(1 for r in records if r.truncated)
            self.store.write_batch(changed, vectors, unchanged,
                                   Checkpoint(entity, stats.run_id, batch.last_key, "running",
                                              stats.rows, resolved.fingerprint, owner))
            stats.timings["store"] += time.perf_counter() - t3
            if progress is not None:
                progress(stats)

        t4 = time.perf_counter()
        stats.deleted = self.store.finish_run(
            Checkpoint(entity, stats.run_id, None, "running", stats.rows, resolved.fingerprint,
                       owner), prune=prune)
        stats.timings["store"] += time.perf_counter() - t4
        return stats
