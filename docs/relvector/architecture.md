# RelVector architecture

## Package layout

```
src/relvector/
  api.py           RelVector facade, read-only connect()
  schema.py        SQLAlchemy inspector -> Schema / TableInfo / ForeignKey
  mapping.py       EntityMapping, resolve() against a schema, deterministic serialisation
  extraction.py    keyset batches, per-relation IN-queries, ROW_NUMBER() caps, SQL validator hook
  embeddings.py    EmbeddingProvider protocol, SentenceTransformerEmbedding, HashingEmbedding
  store.py         VectorStore protocol, LocalVectorStore (SQLite file), SearchResult
  indexing.py      Indexer: extract -> build -> embed changed -> atomic batch write -> prune
  integrations/sqlguard.py   optional SQLGuard Ninja validator
```

The layout is flat on purpose: one module per stage. Each stage boundary is a small protocol
(`EmbeddingProvider`, `VectorStore`, `SqlValidator`), so another backend, provider or a parallel
runner can be added without changing the other stages.

## Origin and reuse decisions

This repository began as a copy of SQLGuard Ninja. These decisions were made when RelVector
was carved out of it:

| Category | Component | Decision |
|---|---|---|
| Reused directly | Packaging pattern (hatchling, `src/` layout, dynamic `_version.py`), ruff/mypy/pytest configuration, Apache-2.0 license, `.gitignore` | Kept and re-pointed at `relvector`. |
| Adapted | `sqlguard_ninja/privacy/suggest.py` sensitive-column name patterns | Ported into `relvector.mapping.sensitive_label`. In RelVector they **block** by default (opt-in via `allow_sensitive`). In SQLGuard they only suggest. |
| Preserved separately | `Guard`, `Policy`, the analysis, lineage, rules and executors | Used only through the public `Guard.validate` API in `relvector.integrations.sqlguard` (optional extra `relvector[sqlguard]`). The core never imports `sqlguard_ninja`. |
| Not reused | `core/lineage.py` | Query lineage is not schema relationship discovery. RelVector uses declared foreign keys from the inspector. |
| Not reused | `integrations/executors.py` | Built for single guarded queries with `max_rows` caps (`fetchmany`), not for streaming extraction. RelVector uses SQLAlchemy Core with keyset pagination. |
| Implemented new | Schema inspection, mapping, extraction, embeddings, vector store, indexing, search | — |

## Separation status

* The repository contains only RelVector: `src/relvector`, `tests/relvector`,
  `examples/relvector` and `docs/relvector`. The SQLGuard Ninja sources, tests, benchmarks,
  docs, deployment files, composite action and workflows were removed from the working tree.
  They remain in git history (the last SQLGuard state is commit `ab646af`). SQLGuard Ninja
  itself is developed in its own repository and published as `sqlguard-ninja`.
* The only remaining SQLGuard dependency is optional: `relvector.integrations.sqlguard` uses the
  public `Guard.validate` API of the installed `sqlguard-ninja` package (extra
  `relvector[sqlguard]`, also in `dev`). Its test skips when that package is absent. The core
  never imports it.
* Attribution: the sensitive-column patterns adapted from SQLGuard Ninja are credited in
  `mapping.py` and `THIRD_PARTY_NOTICES.md`. Both projects are Apache-2.0.
* CI (`.github/workflows/ci.yml`) covers RelVector only, including a PostgreSQL 16 service
  container job. `release.yml` is manual (`workflow_dispatch`) and build-only: it has no
  publish job, no `id-token` permission and no secrets.

## How source changes reach semantic documents

A document is the root row plus its mapped related rows at the moment its batch was read.
Every full run (`index()`) rebuilds every document from current data and compares content
hashes, so on the next completed full run:

| Source change | Effect |
|---|---|
| Root row updated / inserted / deleted | Re-embedded / added / pruned. |
| Child row (one-to-many) updated, inserted, deleted or moved to another parent | Every affected parent document changes: the text and the "N in total" count. Moved children update both parents. |
| Parent row (many-to-one) updated | Every root that references it is re-embedded. A deleted parent reads "Related X n was not found." |
| Unmapped column changed | No effect (the column is never read). |
| Mapping changed | The fingerprint changes, so every document is re-embedded. Resuming an old run is refused. |

Known gaps, by design in this version:

1. **Staleness between runs.** Nothing watches the database. The index is as fresh as the last
   completed run.
2. **No snapshot across a whole run.** Each batch reads its root rows and related rows in one
   transaction. On SQLite that is one snapshot, and PostgreSQL connections use
   `REPEATABLE READ`; `tests/relvector/test_postgres.py` checks that a commit landing between a
   batch's root query and its related-row query is not seen. Different batches can see different moments, so a child that
   moves between parents mid-run can appear under both or neither until the next run.
3. **Resume skips re-reading finished batches.** After `resume=True`, roots before the
   checkpoint key keep the documents built before the interruption, even if their related rows
   changed in between. Rows inserted with keys below the checkpoint are picked up only by the
   next full run. Nothing is wrongly deleted: pruning happens only when a run that still owns
   the checkpoint completes.
4. **Future incremental sync must track every mapped table.** Using only `orders.updated_at`
   would miss shipment and customer edits. An incremental design has to map changes in each
   related table back to root keys through the join column, and handle deletes (tombstones or
   periodic full runs). This is not implemented.
5. **An empty source prunes everything.** If the root table is empty (or every row has a NULL
   primary key), a completed run deletes all of that entity's records. That is correct
   behaviour, but use `prune=False` if an empty result could be a mistake (for example, wrong
   schema or database).
6. **Checkpoint keys are typed.** Date, datetime, time, Decimal, UUID and bytes keys are stored
   with a type tag and restored as the same Python type. On resume, `WHERE pk > :last` compares
   them with the column's own ordering, never as text. This is verified on PostgreSQL for
   `date`, `uuid` and `timestamptz` with values whose text order differs from their natural
   order. Other key types are rejected when a checkpoint is written.
7. **Single writer by takeover, not by lock.** Each `index()` call holds an owner token. A new
   run, or a resume in another process, replaces it, and every batch write and the final prune
   is a compare-and-set on that token. A displaced writer may still embed one more batch, but
   it cannot commit it, advance the checkpoint or prune. There is no lease or heartbeat, so a
   crashed writer never blocks a resume.

## Search performance

`LocalVectorStore.search` streams one SQLite cursor in chunks of `search_chunk_size` rows
(default 1024). Each chunk is decoded into a reused float32 buffer, scored as row-wise float64
sums of products in a reused buffer, pruned against the current k-th best score, and merged
into a heap of at most `top_k` hits. Entity and metadata filters are SQL `WHERE` clauses, so
the vectors of non-matching rows are never decoded. Ranking is by score descending, then
`vector_id` ascending, and does not depend on chunk size or storage order.

Peak memory is about `chunk × dim × 12` bytes for the buffers, plus one chunk of fetched rows,
plus `top_k` hits. It does not depend on the number of vectors. Measured with 20,000 × 64-dim
vectors: 1.6 MB at chunk size 1024, versus 15 MB for the previous load-everything path, which
also kept the full matrix cached between queries.

Remaining limitations:

* **Linear time.** Each query reads and scores every vector that passes the filters, with no
  ANN index. Throughput is bounded by disk/page-cache reads and NumPy per chunk. Removing the
  cross-query matrix cache trades repeated-query speed (now served by SQLite's page cache) for
  bounded memory.
* **Filters are evaluated per row.** `json_extract` runs on every row of the entity, and there
  is no index on metadata values, so a selective filter still costs a full scan of the
  entity's rows (but not vector decoding for rows that fail it). Only exact equality is
  supported.
* **Single-threaded.** No parallel scan over chunks.
* **One long read.** A search holds a SQLite read snapshot for its duration. In WAL mode,
  writers are not blocked.

## Roadmap (not implemented)

1. **Next scalability step: sub-linear search.** Add an ANN backend (FAISS or pgvector)
   behind `VectorStore`. Promote frequently filtered metadata fields to indexed columns so
   filters seek instead of scanning.
2. Multi-hop and composite-key relationships, and explicit child records as separate vectors.
3. Incremental sync driven by `updated_at` columns or a deletion log across every mapped table.
   CDC comes later.
4. Parallel embedding workers behind the `Indexer` batch loop. The owner-token checkpoint
   already gives a single committer.
5. An opt-in remote embedding provider (`sends_data_externally = True`).
6. A CLI (`relvector index config.yaml`) and a mapping config file format.
