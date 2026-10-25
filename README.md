# RelVector

**Schema-aware semantic indexes over existing relational databases.**

RelVector makes selected relational data semantically searchable without migrating or
modifying the source database. It reads your schema, follows declared foreign keys, turns each
root row plus its related rows into deterministic, readable text, embeds it with a
pluggable provider and stores the vectors in a persistent local index. Every search result
points back to the exact source rows.

RelVector does **not** convert a database into a vector database. The database stays the
authoritative source and is only ever read.

> Status: `0.1.0`, alpha. Tested with SQLite and PostgreSQL 16. APIs may change before 1.0.

## Install

Python 3.11+:

```bash
pip install relvector                # core: SQLAlchemy + NumPy
pip install "relvector[local]"       # + sentence-transformers for local embeddings (pulls in PyTorch)
pip install "relvector[postgres]"    # + psycopg 3; use postgresql+psycopg://user@host/db URLs
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
* Re-indexing is a full re-scan. There is no change-data-capture, and no triggers or timestamps
  are used. Edits to related rows (child shipments, a parent customer) are picked up on the
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
  pass the filters. Latency grows linearly with index size, and there is no approximate (ANN)
  index. See [search performance](docs/relvector/architecture.md#search-performance).
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
