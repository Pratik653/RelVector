# Changelog

All notable changes are listed here. The project follows semantic versioning once released.

## 0.2.0rc1 (release candidate)

Added (all opt-in; v0.1.0 behaviour and APIs are unchanged):

* **Incremental sync.** `configure(change_tracking={table: column, ...}, soft_delete=...)` and
  `rv.sync(batch_size, lookback=..., full_fallback=False) -> SyncStats`.
  * Changed rows are read per mapped table in bounded `(tracking column, pk)` keyset batches,
    starting at `watermark - lookback`.
  * Affected root documents are rebuilt, including the previous parents of reassigned
    children, which are found through the index's provenance.
  * Per-table watermarks are committed atomically with each batch.
  * `index()` records watermarks captured before its scan.
  * Missing tracking columns or stale watermarks fail clearly (`MappingError`,
    `SyncUnavailableError`).
* **Optional FAISS backend.** `vector_store="faiss"` / `FaissVectorStore` (`pip install
  "relvector[faiss]"`).
  * A CPU `IndexIVFFlat` derived from the SQLite store, with ANN candidates re-scored
    exactly.
  * Exact fallback for metadata filters, a requested entity in a multi-entity index, or a
    small index.
  * Crash-safe through a dirty marker, atomic saves and automatic rebuild from SQLite.
* **Store contract.**
  * `Checkpoint.state`: durable, typed, and committed with each claim.
  * `VectorStore.delete_records`: owner-checked.
  * `VectorStore.referencing`: an indexed reverse lookup from related-row primary keys to the
    documents that reference them.
  * A post-commit `_after_commit` hook for derived indexes.

Compatibility: index files written by 0.1.0 open in place. The new checkpoint `state` column
and the reference lookup table are added and backfilled on first open. This migration is
one-way. After it, 0.1.0 can still open and search the file, but indexing with 0.1.0 fails
with `OperationalError` (rv_checkpoints has 9 columns). There is no silent corruption. To
go back, rebuild the index with 0.1.0 at a new path. FAISS files are derived and can be
deleted at any time.

## 0.1.0 (2026-10-25)

First public release:

* Read-only connections for SQLite (`mode=ro`) and PostgreSQL (read-only `REPEATABLE READ`
  transactions).
* Schema inspection: tables, columns, primary keys and foreign keys.
* Entity mappings with one-hop related tables, explicit `Include(via=...)` joins,
  sensitive-field blocking, exclusions and deterministic templates.
* Bounded keyset extraction with per-relation `IN` queries and `ROW_NUMBER()` caps that report
  truncation.
* Embedding providers: local sentence-transformers and dependency-free hashing.
* A persistent SQLite vector store with exact cosine search and metadata filters.
* Idempotent re-indexing with content hashes, pruning of deleted rows, atomic per-batch
  checkpoints, typed checkpoint keys (date, datetime, UUID, Decimal), resume, and single-writer
  ownership (`RunSupersededError`).
* Optional SQLGuard Ninja validation of extraction queries.
* Streaming exact search: chunked cursor reads, a bounded top-k heap, SQL-side filtering and
  deterministic tie-breaking. Search memory no longer grows with index size
  (`LocalVectorStore(search_chunk_size=...)`).
* PostgreSQL validation tests on a disposable database.
