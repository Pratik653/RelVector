"""Focused tests for the RelVector vertical slice (deterministic hashing embeddings)."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import text

from relvector import (
    EntityMapping,
    HashingEmbedding,
    Include,
    IndexMismatchError,
    MappingError,
    RelVector,
    SensitiveFieldError,
)
from relvector.mapping import build_record, resolve

TEMPLATES = {"orders": "Order {id} is {status}.",
             "shipments": "Its associated shipment has a {delay_reason}."}


def make_rv(db: Path, index: Path, provider=None, **kw) -> RelVector:
    return RelVector(f"sqlite:///{db}", embedding_provider=provider or HashingEmbedding(256),
                     index_path=index, **kw)


def configure(rv: RelVector, **overrides):
    opts = {"root_table": "orders", "include_tables": ["shipments"],
            "text_fields": ["orders.status", "shipments.delay_reason"],
            "metadata_fields": ["orders.status"], "templates": TEMPLATES}
    opts.update(overrides)
    return rv.configure(**opts)


def test_schema_inspection_and_foreign_keys(shop_db, tmp_path):
    with make_rv(shop_db, tmp_path / "i.rv") as rv:
        schema = rv.inspect_schema()
    assert set(schema.tables) == {"customers", "orders", "shipments"}
    assert schema.table("orders").primary_key == ("id",)
    assert schema.table("shipments").column("delay_reason").nullable
    fks = {str(fk) for fk in schema.foreign_keys}
    assert fks == {"orders(customer_id) -> customers(id)", "shipments(order_id) -> orders(id)"}


def test_relationship_resolution(shop_db, tmp_path):
    with make_rv(shop_db, tmp_path / "i.rv") as rv:
        schema = rv.inspect_schema()
    resolved = resolve(EntityMapping(
        root_table="orders", include=["shipments", "customers"],
        text_fields=["status", "shipments.delay_reason", "customers.segment"]), schema)
    kinds = {r.table: (r.kind, r.root_column, r.related_column) for r in resolved.relations}
    assert kinds == {"shipments": ("one_to_many", "id", "order_id"),
                     "customers": ("many_to_one", "customer_id", "id")}
    explicit = resolve(EntityMapping(
        root_table="orders", include=[Include("shipments", via=("orders.id", "shipments.order_id"))],
        text_fields=["shipments.delay_reason"]), schema)
    assert explicit.relations[0].kind == "one_to_many"
    with pytest.raises(MappingError, match="neither the root table"):
        resolve(EntityMapping(root_table="orders", text_fields=["shipments.delay_reason"]), schema)
    with pytest.raises(MappingError, match="no single-column foreign key"):
        resolve(EntityMapping(root_table="shipments", include=["customers"],
                              text_fields=["customers.segment"]), schema)


def test_deterministic_semantic_records(shop_db, tmp_path):
    with make_rv(shop_db, tmp_path / "i.rv") as rv:
        resolved = configure(rv)
        batches = list(rv.extractor().iter_batches(10))
    bundles = {b.row["id"]: b for b in batches[0].bundles}
    rec = build_record(resolved, bundles[1002].row, bundles[1002].related)
    assert rec.text == "Order 1002 is delayed. Its associated shipment has a carrier capacity shortage."
    assert rec.source_pk == {"id": 1002}
    assert rec.references == [{"table": "shipments", "relation": "one_to_many", "pk": {"id": 502}}]
    assert rec.metadata == {"orders.status": "delayed"}
    again = build_record(resolved, bundles[1002].row, bundles[1002].related)
    assert again.content_hash == rec.content_hash and again.vector_id == rec.vector_id == "orders:[1002]"
    # A null in a templated field falls back to explicit, non-inferring text.
    null = build_record(resolved, bundles[1001].row, bundles[1001].related)
    assert null.text == "Order 1001 is delivered. Shipment 501. Delay reason: not recorded."
    assert build_record(resolved, bundles[1004].row, bundles[1004].related).text.endswith(
        "No related shipments.")


def test_sensitive_fields_blocked_and_never_selected(shop_db, tmp_path):
    seen: list[str] = []
    with make_rv(shop_db, tmp_path / "i.rv", sql_validator=seen.append) as rv:
        with pytest.raises(SensitiveFieldError, match=r"customers\.email"):
            configure(rv, include_tables=["customers"], text_fields=["customers.email"])
        with pytest.raises(MappingError, match="also in exclude_fields"):
            configure(rv, include_tables=["customers"], text_fields=["customers.segment"],
                      metadata_fields=["customers.segment"], exclude_fields=["customers.segment"])
        configure(rv, include_tables=["customers"], text_fields=["customers.segment"],
                  exclude_fields=["customers.email"], templates={})
        rv.index(batch_size=2)
        assert seen and not any("email" in sql for sql in seen)
        hits = rv.search("retail", top_k=10)
        assert all("@" not in h.text and "email" not in str(h.metadata) for h in hits)
        # Explicit authorisation is the only way to embed a sensitive-looking column.
        configure(rv, include_tables=["customers"], text_fields=["customers.email"],
                  allow_sensitive=["customers.email"], templates={})


def test_bounded_keyset_batches_and_reported_truncation(shop_db, tmp_path):
    seen: list[str] = []
    with make_rv(shop_db, tmp_path / "i.rv", sql_validator=seen.append) as rv:
        resolved = configure(rv, max_children=2, templates={})
        batches = list(rv.extractor().iter_batches(2))
    assert [len(b.bundles) for b in batches] == [2, 2, 1]
    assert [b.last_key for b in batches] == [[1002], [1004], [1005]]
    # Keyset pagination: later pages filter on the last key. (SQLAlchemy's SQLite dialect always
    # renders "LIMIT ? OFFSET ?" with offset 0; the offset is never advanced.)
    roots = [s for s in seen if "FROM orders" in s]
    assert "orders.id >" not in roots[0] and all("orders.id > :id_1" in s for s in roots[1:])
    assert any("row_number()" in s.lower() for s in seen)
    b = next(x for x in batches[-1].bundles if x.row["id"] == 1005)
    rows, total = b.related["shipments"]
    assert (len(rows), total) == (2, 3)
    rec = build_record(resolved, b.row, b.related)
    assert rec.truncated == {"shipments": 1}
    assert "3 in total, showing the first 2" in rec.text


def test_persistent_round_trip_and_source_references(shop_db, tmp_path):
    index = tmp_path / "i.rv"
    with make_rv(shop_db, index) as rv:
        configure(rv)
        stats = rv.index(batch_size=2)
        assert (stats.rows, stats.embedded, stats.batches) == (5, 5, 3)
    with make_rv(shop_db, index) as rv:  # reload from disk, no re-indexing
        configure(rv)
        hits = rv.search("carrier capacity shortage", top_k=3)
        assert hits[0].source_table == "orders" and hits[0].source_pk == {"id": 1002}
        assert hits[0].references[0] == {"table": "shipments", "relation": "one_to_many",
                                         "pk": {"id": 502}}
        assert hits[0].score >= hits[1].score >= hits[2].score
        delayed = rv.search("shipment", top_k=10, filters={"orders.status": "delayed"})
        assert {h.source_pk["id"] for h in delayed} == {1002, 1003, 1005}
    with make_rv(shop_db, index, provider=HashingEmbedding(128)) as rv:
        configure(rv)
        with pytest.raises(IndexMismatchError):
            rv.index()


def test_reindex_is_idempotent_and_tracks_changes(shop_db, tmp_path):
    index = tmp_path / "i.rv"
    with make_rv(shop_db, index) as rv:
        configure(rv)
        rv.index(batch_size=2)
        again = rv.index(batch_size=3)
        assert (again.embedded, again.unchanged, again.deleted) == (0, 5, 0)
        assert rv.store.count() == 5
        with sqlite3.connect(shop_db) as conn:
            conn.execute("UPDATE shipments SET delay_reason = 'flooded road' WHERE id = 503")
            conn.execute("DELETE FROM shipments WHERE order_id = 1004")
            conn.execute("DELETE FROM orders WHERE id = 1004")
        conn.close()
        changed = rv.index(batch_size=2)
        assert (changed.embedded, changed.unchanged, changed.deleted) == (1, 3, 1)
        assert rv.store.count() == 4
        assert "flooded road" in rv.search("flooded road", top_k=1)[0].text


class FailingProvider(HashingEmbedding):
    def __init__(self, fail_on_call: int) -> None:
        super().__init__(256)
        self.calls, self.fail_on_call = 0, fail_on_call

    def embed(self, texts):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("embedding service down")
        return super().embed(texts)


def test_interrupted_run_resumes_without_duplicates_or_pruning(shop_db, tmp_path):
    index = tmp_path / "i.rv"
    with make_rv(shop_db, index, provider=FailingProvider(fail_on_call=2)) as rv:
        configure(rv)
        with pytest.raises(RuntimeError):
            rv.index(batch_size=2)
        assert rv.store.count() == 2  # first batch committed, nothing pruned
        cp = rv.store.checkpoint("orders")
        assert (cp.status, cp.last_key) == ("running", [1002])
        resumed = rv.index(batch_size=2, resume=True)
        assert resumed.resumed and resumed.embedded == 3 and resumed.deleted == 0
        assert rv.store.count() == 5
        assert rv.store.checkpoint("orders").status == "completed"


def test_source_database_is_read_only_and_unchanged(shop_db, tmp_path):
    before = hashlib.sha256(shop_db.read_bytes()).hexdigest()
    with make_rv(shop_db, tmp_path / "i.rv") as rv:
        configure(rv)
        rv.index(batch_size=2)
        with rv.engine.connect() as conn, pytest.raises(Exception, match="readonly"):
            conn.execute(text("DELETE FROM orders"))
        assert "readonly" not in repr(rv)  # repr must not leak connection details beyond URL
    assert hashlib.sha256(shop_db.read_bytes()).hexdigest() == before
    with pytest.raises(Exception, match="not found"):
        RelVector(f"sqlite:///{tmp_path / 'missing.db'}", embedding_provider="hashing",
                  index_path=tmp_path / "x.rv")
    assert not (tmp_path / "missing.db").exists()


def test_external_provider_requires_opt_in(shop_db, tmp_path):
    class Remote(HashingEmbedding):
        sends_data_externally = True

    with pytest.raises(Exception, match="allow_external_embeddings"):
        make_rv(shop_db, tmp_path / "i.rv", provider=Remote())
    make_rv(shop_db, tmp_path / "j.rv", provider=Remote(), allow_external_embeddings=True).close()


def test_hashing_embedding_is_deterministic_and_normalised():
    a, b = HashingEmbedding(64).embed(["late truck", "late truck"])
    assert np.array_equal(a, b) and abs(float(np.linalg.norm(a)) - 1.0) < 1e-6


def test_sqlguard_validator_allows_and_blocks(shop_db, tmp_path):
    sqlguard = pytest.importorskip("sqlguard_ninja")
    from relvector import QueryRejectedError
    from relvector.integrations.sqlguard import SQLGuardValidator

    def guard(tables):
        policy = sqlguard.Policy.from_dict({
            "name": "rv-test", "dialect": "sqlite",
            "catalog": {"tables": {
                "orders": {"columns": {"id": "integer", "customer_id": "integer",
                                       "status": "text"}},
                "shipments": {"columns": {"id": "integer", "order_id": "integer",
                                          "delay_reason": "text"}},
            }},
            "roles": {"indexer": {"tables": dict.fromkeys(tables, "*"), "tenant_scoped": False}},
        })
        return SQLGuardValidator(sqlguard.Guard(policy), role="indexer", dialect="sqlite")

    with make_rv(shop_db, tmp_path / "i.rv", sql_validator=guard(["orders", "shipments"])) as rv:
        configure(rv)
        assert rv.index(batch_size=2).rows == 5
    with make_rv(shop_db, tmp_path / "j.rv", sql_validator=guard(["orders"])) as rv:
        configure(rv)
        with pytest.raises(QueryRejectedError, match="SQLGuard blocked"):
            rv.index(batch_size=2)
        assert rv.store.count() == 0


@pytest.mark.model
def test_local_sentence_transformer_smoke(shop_db, tmp_path):
    pytest.importorskip("sentence_transformers")
    from relvector import SentenceTransformerEmbedding

    provider = SentenceTransformerEmbedding(local_files_only=True)
    try:
        assert provider.dimension > 0
    except Exception as exc:  # model not cached locally: never download in the test suite
        pytest.skip(f"model not available offline: {exc}")
    with make_rv(shop_db, tmp_path / "i.rv", provider=provider) as rv:
        configure(rv)
        rv.index(batch_size=2)
        hits = rv.search("orders held up by transportation problems", top_k=3)
    assert hits[0].source_pk["id"] in {1002, 1003, 1005}
    assert {h.source_pk["id"] for h in hits} <= {1002, 1003, 1005, 1001, 1004}


def test_superseded_run_stops_without_pruning(shop_db, tmp_path):
    from relvector import RunSupersededError

    index = tmp_path / "i.rv"

    class Interloper(HashingEmbedding):
        """On its second call, a separate process-like RelVector completes a full run."""

        def __init__(self) -> None:
            super().__init__(256)
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            if self.calls == 2:
                with make_rv(shop_db, index) as other:
                    configure(other)
                    assert other.index(batch_size=5).rows == 5
            return super().embed(texts)

    with make_rv(shop_db, index, provider=Interloper()) as rv:
        configure(rv)
        with pytest.raises(RunSupersededError):
            rv.index(batch_size=2)
        assert rv.store.count() == 5  # the newer run's records all survive
        assert rv.store.checkpoint("orders").status == "completed"


def test_resume_refuses_changed_mapping(shop_db, tmp_path):
    with make_rv(shop_db, tmp_path / "i.rv", provider=FailingProvider(fail_on_call=2)) as rv:
        configure(rv)
        with pytest.raises(RuntimeError):
            rv.index(batch_size=2)
        configure(rv, templates={})
        with pytest.raises(Exception, match="mapping changed"):
            rv.index(batch_size=2, resume=True)
        assert rv.store.count() == 2  # nothing pruned or rewritten
        assert rv.index(batch_size=2).rows == 5  # a fresh full run is fine


def test_related_row_changes_reach_documents(shop_db, tmp_path):
    with make_rv(shop_db, tmp_path / "i.rv") as rv:
        configure(rv, include_tables=["shipments", "customers"],
                  text_fields=["orders.status", "shipments.delay_reason", "customers.segment"])
        rv.index(batch_size=2)
        with sqlite3.connect(shop_db) as conn:
            conn.execute("UPDATE customers SET segment = 'enterprise' WHERE id = 2")  # 1003, 1005
            conn.execute("INSERT INTO shipments VALUES (507, 1002, 'driver shortage')")
        conn.close()
        stats = rv.index(batch_size=2)
        assert (stats.embedded, stats.unchanged, stats.deleted) == (3, 2, 0)
        texts = {h.source_pk["id"]: h.text for h in rv.search("order", top_k=10)}
        assert "driver shortage" in texts[1002]
        assert "enterprise" in texts[1003] and "enterprise" in texts[1005]


def test_rows_with_null_primary_key_are_skipped(tmp_path):
    db = tmp_path / "codes.db"
    with sqlite3.connect(db) as conn:  # SQLite allows NULL in a non-INTEGER primary key
        conn.execute("CREATE TABLE codes (code TEXT PRIMARY KEY, label TEXT)")
        conn.executemany("INSERT INTO codes VALUES (?, ?)",
                         [(None, "orphan"), ("A", "alpha"), ("B", "beta")])
    conn.close()
    with make_rv(db, tmp_path / "i.rv") as rv:
        rv.configure(root_table="codes", text_fields=["label"])
        assert rv.index(batch_size=1).rows == 2
        assert {h.source_pk["code"] for h in rv.search("alpha", top_k=5)} == {"A", "B"}


def test_checkpoint_keys_keep_type_and_order():
    import datetime as dt
    import json
    import uuid
    from decimal import Decimal

    from relvector.store import decode_key, encode_key

    keys = [
        [dt.date(2024, 1, 9)], [dt.datetime(2024, 1, 9, 8, 30, tzinfo=dt.UTC)],
        [Decimal("10.50")], [uuid.UUID(int=255)], [b"\x00\xff"], [1, "a", 2.5, True, None],
        [dt.time(23, 59, 1)],
    ]
    for key in keys:
        back = decode_key(json.loads(json.dumps(encode_key(key))))
        assert back == key and [type(v) for v in back] == [type(v) for v in key]
    # Text encodings would mis-order: "10" < "9" as text, but resumed keys compare as numbers.
    assert decode_key(encode_key([Decimal(9)]))[0] < decode_key(encode_key([Decimal(10)]))[0]
    with pytest.raises(Exception, match="cannot be checkpointed"):
        encode_key([object()])


def test_concurrent_resume_of_same_run_is_rejected(shop_db, tmp_path):
    from relvector import RunSupersededError
    from relvector.store import Checkpoint

    index = tmp_path / "i.rv"
    with make_rv(shop_db, index, provider=FailingProvider(fail_on_call=2)) as rv:
        configure(rv)
        with pytest.raises(RuntimeError):
            rv.index(batch_size=2)
        cp = rv.store.checkpoint("orders")

    class SecondResumer(HashingEmbedding):
        """While this writer embeds, another process resumes the same run."""

        def embed(self, texts):
            with make_rv(shop_db, index) as other:
                other.store.resume_run(Checkpoint(cp.entity, cp.run_id, cp.last_key, "running",
                                                  cp.processed, cp.fingerprint, "other-writer"))
            return super().embed(texts)

    with make_rv(shop_db, index, provider=SecondResumer(256)) as rv:
        configure(rv)
        with pytest.raises(RunSupersededError):
            rv.index(batch_size=2, resume=True)
        after = rv.store.checkpoint("orders")
        assert (after.status, after.owner, after.last_key) == ("running", "other-writer", [1002])
        assert rv.store.count() == 2  # the rejected writer wrote nothing and pruned nothing
