# RelVector

**Schema-aware semantic indexes over existing relational databases.**

RelVector makes selected relational data semantically searchable without migrating or
modifying the source database. It reads your schema, follows declared foreign keys, turns each
root row plus its related rows into deterministic, readable text, embeds it with a
pluggable provider and stores the vectors in a persistent local index. Every search result
points back to the exact source rows.

RelVector does **not** convert a database into a vector database. The database stays the
authoritative source and is only ever read.

> Status: `0.2.0rc1` (release candidate), alpha. Tested with SQLite and PostgreSQL 16. APIs may change before 1.0.

## Install

Python 3.11+:

```bash
pip install relvector                # core: SQLAlchemy + NumPy
pip install "relvector[local]"       # + sentence-transformers for local embeddings (pulls in PyTorch)
pip install "relvector[postgres]"    # + psycopg 3; use postgresql+psycopg://user@host/db URLs
pip install "relvector[faiss]"       # + faiss-cpu for the optional approximate (ANN) backend
pip install "relvector[sqlguard]"    # + optional SQLGuard Ninja query validation
```

For development, use `pip install -e ".[dev]"` from a checkout.

## Quick start

```python
from relvector import RelVector

with RelVector("sqlite:///shop.db", embedding_provider="local",
               index_path="shop.rvindex") as rv:
    print(rv.inspect_schema().describe())        # tables, columns, PKs, foreign keys

    rv.configure(
        root_table="orders",                     # one semantic record per order
        include_tables=["shipments"],            # joined via the declared foreign key
        text_fields=["orders.status", "shipments.delay_reason"],   # embedded
        metadata_fields=["orders.status"],       # stored and filterable, not embedded
        exclude_fields=["customers.email"],
        templates={
            "orders": "Order {id} is {status}.",
            "shipments": "Its associated shipment has a {delay_reason}.",
        },
    )
    stats = rv.index(batch_size=500)
    print(stats)   # rows, embedded, unchanged, deleted, timings, rows/s

    for hit in rv.search("orders delayed because of transport problems", top_k=5):
        print(hit.score, hit.source_table, hit.source_pk, hit.references)
        print(hit.text)
```

The record for order 1002 reads:
`Order 1002 is delayed. Its associated shipment has a carrier capacity shortage.`

Runnable example: [examples/relvector/orders_shipments.py](examples/relvector/orders_shipments.py)
(`--provider hashing` runs without any model).

## Incremental sync (opt-in)

If every mapped table has a column that your application reliably sets on insert *and*
update, `sync()` re-indexes only what changed:

```python
rv.configure(
    root_table="orders", include_tables=["shipments"],
    text_fields=["orders.status", "shipments.delay_reason"],
    change_tracking={"orders": "updated_at", "shipments": "updated_at"},  # every mapped table
    soft_delete="deleted_at",            # optional: root rows with a non-NULL value are removed
)
rv.index()                               # a full run first; records the starting watermarks
stats = rv.sync(lookback=timedelta(minutes=5))   # later: only changed rows, in bounded batches
```

What `sync()` guarantees:

* Rows are read in `(tracking column, pk)` order from `watermark - lookback`, using `>=` so
  equal timestamps are never skipped, up to the maximum value read when that table's scan
  starts. The default lookback is 5 minutes for date/time columns and 0 for numeric ones.
* Which documents are rebuilt:
  * A changed root row rebuilds itself.
  * A changed child rebuilds its current parent and its previous parent. The previous parent
    comes from the index's own provenance, so a reassigned shipment leaves neither order stale.
  * A changed many-to-one parent rebuilds every root that references it.
  * Roots whose row is gone or soft-deleted are removed.
* Rebuilt documents go through the same deterministic mapping and hashing as `index()`, and
  only changed content is re-embedded.
* Each batch's watermark is committed in the same transaction as that batch's index changes.
  An interrupted sync can just be run again.

What it does **not** guarantee:

* **Numeric tracking columns get no lookback by default.** Values allocated from a sequence
  can commit out of order (a transaction holding 41 may commit after 42 was read), so set
  `lookback` to a number that covers the values that can be in flight at once.
* It misses changes whose tracking value is older than `watermark - lookback`. Examples are
  transactions that commit later than the lookback, clock skew between writers, backfills
  with old timestamps, and code paths that don't bump the column. Rows with a NULL tracking
  value are never seen.
* Hard deletes are invisible to timestamps. Run a full `index()` periodically to reconcile;
  it prunes them. A soft delete must also bump the root's tracking column.
* Many-to-one changes are missed in three cases: a parent's primary key changes, a parent is
  hard-deleted, or a root's FK changes without its tracking column being bumped.
* Rows sitting inside the lookback window are re-read on every sync. They are skipped by
  content hash, so this is cheap, but a bulk load that shares one timestamp is re-read until
  newer changes move the watermark past it.

If a mapped table has no tracking column, `sync()` raises `MappingError`. If watermarks are
missing or stale (no full index yet, or the mapping or tracking changed), it raises
`SyncUnavailableError`. `sync(full_fallback=True)` runs `index()` instead. This is a
timestamp-based sync, not change-data-capture.

## Optional FAISS backend (approximate search)

```python
rv = RelVector(url, vector_store="faiss", index_path="shop.rvindex")   # pip install "relvector[faiss]"
# or tune it: RelVector(url, vector_store=FaissVectorStore("shop.rvindex", ann_min_vectors=5000))
```

* SQLite stays the source of truth. A FAISS `IndexIVFFlat` file (inner product on normalised
  vectors) sits next to it and is rebuilt from SQLite automatically if it is missing,
  unreadable, flagged dirty after a crash, or inconsistent with SQLite.
* Search is **approximate**: FAISS proposes `top_k × oversample` candidates, and these are
  re-scored exactly. Returned scores are therefore true cosine similarities, but a true
  nearest neighbour can be missed (recall below 1). `store.last_search_mode` reports `"ann"`
  or `"exact"`.
* The FAISS backend falls back to exact search in three cases: metadata `filters` are given,
  the index holds several entities and one is requested, or there are fewer than
  `ann_min_vectors` (default 5000) vectors. Filtered results are therefore never truncated by
  the ANN step.
* Upserts, `sync()`, deletes and pruning keep the FAISS index current. It is saved atomically
  at the end of each run and on close. Use one writer process per index.

## How it works

| Stage | Behaviour |
|---|---|
| Inspect | SQLAlchemy inspector: tables, columns, primary keys, declared foreign keys. Catalog only, no rows. |
| Map | `EntityMapping`: root table, directly related tables (FK or explicit `Include(via=...)`), `text_fields`, `metadata_fields`, `exclude_fields`. Only listed columns are ever selected. |
| Extract | Keyset pagination on the primary key (`WHERE pk > :last ORDER BY pk LIMIT n`). Related rows are fetched per batch with `IN (...)`, one query per relation, so there are no joins and no Cartesian products. One-to-many relations are capped per parent with `ROW_NUMBER()`, the true count is reported in the text and in `truncated`. |
| Serialise | Deterministic templates. Nulls render as "not recorded"; if a templated field is null, the record falls back to explicit `Field: value.` text instead of producing a misleading sentence. No LLM is involved. |
| Embed | `"local"` = sentence-transformers (default `all-MiniLM-L6-v2`), `"hashing"` = dependency-free lexical hashing, or any object implementing `EmbeddingProvider`. |
| Store | `LocalVectorStore`: one SQLite file with float32 vectors, JSON metadata and checkpoints. No pickle. Exact cosine search, streamed in bounded chunks (memory does not grow with the index). |
| Re-index | Idempotent: vector ids are derived from the primary key, unchanged content (by hash) is not re-embedded, rows that disappeared are pruned when a run completes. Each batch commits atomically with its checkpoint; `index(resume=True)` continues an interrupted run. |

Search results carry `vector_id`, `score`, `text`, `source_table`, `source_pk`, `metadata`,
`references` (the related rows used, by primary key) and `truncated`. Metadata can be filtered
exactly: `rv.search(q, filters={"orders.status": "delayed"})`.

**A high similarity score is not evidence of causation or of a fact.** It means the text of
a record is close to the query in embedding space. Check the source rows.

## Safety defaults

* Source connections are read-only: SQLite opens with `mode=ro` (a missing file is an error,
  never created); PostgreSQL sessions use `READ ONLY`, `REPEATABLE READ` transactions. Use a
  read-only database role as well. If you pass your own `engine=`, these settings are yours to
  configure.
* Only `SELECT` statements built with SQLAlchemy Core run, with bound parameters. There is no
  free-form SQL input.
* Columns whose names look sensitive (email, phone, password, SSN, card number and so on) are
  refused in `text_fields`/`metadata_fields` unless listed in `allow_sensitive`. Name heuristics
  are incomplete: `notes` may hold anything, so review every field you map.
* Providers that send text off the machine must declare `sends_data_externally = True` and
  are refused unless you pass `allow_external_embeddings=True`.
* `repr()` hides passwords in connection URLs.
* Optional [SQLGuard Ninja](https://pypi.org/project/sqlguard-ninja/) integration validates every extraction
  query against a policy and blocks on denial:

  ```python
  from sqlguard_ninja import Guard, Policy
  from relvector.integrations.sqlguard import SQLGuardValidator

  rv = RelVector(url, sql_validator=SQLGuardValidator(Guard(Policy.from_file("policy.yaml")),
                                                      role="indexer"))
  ```

  SQLGuard approval means the query is allowed for the role. It does not mean the values may
  be embedded and stored; that decision belongs to the mapping.

## Known limitations

* This is a trusted-developer library. The index file contains embedded text and metadata in
  plain form. Anyone who can read it can read that data. There is no row-level or tenant
  isolation in the index.
* Relationships: one hop from the root table, single-column joins. No self-references,
  multi-hop paths or composite foreign keys yet. Composite root primary keys are supported.
* `index()` is a full re-scan. `sync()` is timestamp-based and has the limits listed under
  [Incremental sync](#incremental-sync-opt-in). Neither is change-data-capture. Edits to related rows (child shipments, a parent customer) are picked up on the
  next completed run. Rows changed during a run may be read at different moments, and the next
  run corrects them. See
  [how source changes reach documents](docs/relvector/architecture.md#how-source-changes-reach-semantic-documents).
* Only one writer per entity at a time. A new run, or a resume of the same run in another
  process, takes over the checkpoint. The displaced writer stops with `RunSupersededError` at
  its next batch and never prunes. This is a takeover, not a lock: it doesn't stop two writers
  from embedding the same batch, and those duplicate writes are harmless upserts.
* Checkpoints keep primary-key types (int, str, date, datetime, time, Decimal, UUID, bytes), so
  a resumed scan compares keys as the column does. Other key types cannot be checkpointed and
  fail with a clear error.
* `LocalVectorStore` search is exact and streamed: memory is bounded by
  `search_chunk_size` (default 1024 rows) and `top_k`, but every query scans all vectors that
  pass the filters, so latency grows linearly with index size. The optional FAISS backend
  is sub-linear but approximate, and filtered queries on it are still exact and linear. See
  [search performance](docs/relvector/architecture.md#search-performance).
* The hashing provider is lexical, not semantic.
* SQLite and PostgreSQL only. Other databases are not supported.

## Development

```bash
pip install -e ".[dev]"
pytest                      # model and PostgreSQL tests skip unless available (see CONTRIBUTING.md)
ruff check src/relvector tests/relvector examples/relvector
mypy
```

Architecture, reuse decisions and roadmap: [docs/relvector/architecture.md](docs/relvector/architecture.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This
repository grew out of SQLGuard Ninja (same authors and licence), whose history it keeps.
