# Changelog

All notable changes are listed here. The project follows semantic versioning once released.

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
