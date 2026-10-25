"""The :class:`RelVector` facade: connect, inspect, configure, index, search."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url

from relvector.embeddings import EmbeddingProvider, get_provider
from relvector.errors import MappingError, RelVectorError
from relvector.extraction import Extractor, SqlValidator
from relvector.indexing import Indexer, IndexStats
from relvector.mapping import EntityMapping, Include, ResolvedMapping, resolve
from relvector.schema import Schema, inspect_schema
from relvector.store import LocalVectorStore, SearchResult, VectorStore

SUPPORTED_DIALECTS = ("sqlite", "postgresql")


def connect(source_url: str) -> Engine:
    """Create a read-only engine for a SQLite file or a PostgreSQL database.

    SQLite files are opened with ``mode=ro`` (a missing file is an error, never silently
    created); PostgreSQL sessions are set to ``READ ONLY`` transactions. Read-only mode is a
    safety net; the database role should also be read-only.
    """
    url = make_url(source_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        if not url.database or url.database == ":memory:":
            raise RelVectorError("an in-memory SQLite URL has no data to index; pass engine=")
        path = Path(url.database).resolve()
        if not path.is_file():
            raise RelVectorError(f"SQLite database not found: {path}")
        uri = f"{path.as_uri()}?mode=ro"
        return create_engine(
            "sqlite://",
            creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False),
        )
    if backend == "postgresql":
        # REPEATABLE READ gives each batch's root and related-row queries one snapshot.
        return create_engine(source_url, execution_options={
            "postgresql_readonly": True, "isolation_level": "REPEATABLE READ"})
    raise RelVectorError(f"unsupported database {backend!r}; supported: "
                         f"{', '.join(SUPPORTED_DIALECTS)}")


class RelVector:
    """Semantic index over selected relational data; the source database stays authoritative.

    Example::

        rv = RelVector("sqlite:///shop.db", embedding_provider="local",
                       index_path="shop.rvindex")
        rv.configure(root_table="orders", include_tables=["shipments"],
                     text_fields=["orders.status", "shipments.delay_reason"],
                     metadata_fields=["orders.status"])
        rv.index(batch_size=500)
        for hit in rv.search("orders delayed by transport problems", top_k=5):
            print(hit.score, hit.source_pk, hit.text)
    """

    def __init__(
        self,
        source_url: str | None = None,
        *,
        engine: Engine | None = None,
        embedding_provider: str | EmbeddingProvider = "local",
        vector_store: str | VectorStore = "local",
        index_path: str | Path = "relvector_index.sqlite",
        schema: str | None = None,
        sql_validator: SqlValidator | None = None,
        allow_external_embeddings: bool = False,
    ) -> None:
        if (source_url is None) == (engine is None):
            raise RelVectorError("pass exactly one of source_url or engine")
        self.engine = engine if engine is not None else connect(source_url)  # type: ignore[arg-type]
        self.source = (make_url(source_url).render_as_string(hide_password=True) if source_url
                       else engine.url.render_as_string(hide_password=True))  # type: ignore[union-attr]
        self.provider = get_provider(embedding_provider)
        if self.provider.sends_data_externally and not allow_external_embeddings:
            raise RelVectorError(
                f"embedding provider {self.provider.model_id!r} sends source text to an external "
                "service; pass allow_external_embeddings=True to opt in explicitly"
            )
        if isinstance(vector_store, str):
            if vector_store != "local":
                raise RelVectorError(f"unknown vector store {vector_store!r}; use 'local'")
            self.store: VectorStore = LocalVectorStore(index_path)
        else:
            self.store = vector_store
        self.db_schema = schema
        self.sql_validator = sql_validator
        self._schema: Schema | None = None
        self._mapping: ResolvedMapping | None = None

    def __repr__(self) -> str:
        return f"RelVector(source={self.source!r}, provider={self.provider.model_id!r})"

    def __enter__(self) -> RelVector:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.store.close()
        self.engine.dispose()

    def inspect_schema(self, *, refresh: bool = False) -> Schema:
        if self._schema is None or refresh:
            self._schema = inspect_schema(self.engine, schema=self.db_schema)
        return self._schema

    def configure(
        self,
        mapping: EntityMapping | None = None,
        *,
        root_table: str | None = None,
        include_tables: Sequence[str | Include] = (),
        text_fields: Sequence[str] = (),
        metadata_fields: Sequence[str] = (),
        exclude_fields: Sequence[str] = (),
        allow_sensitive: Sequence[str] = (),
        templates: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
        name: str | None = None,
        version: str = "1",
        max_children: int = 20,
    ) -> ResolvedMapping:
        """Set the entity mapping (pass an :class:`EntityMapping` or keyword arguments)."""
        if mapping is None:
            if root_table is None:
                raise MappingError("root_table is required")
            mapping = EntityMapping(
                root_table=root_table, include=tuple(include_tables),
                text_fields=tuple(text_fields), metadata_fields=tuple(metadata_fields),
                exclude_fields=tuple(exclude_fields), allow_sensitive=tuple(allow_sensitive),
                templates=dict(templates or {}), labels=dict(labels or {}), name=name,
                version=version, max_children=max_children,
            )
        self._mapping = resolve(mapping, self.inspect_schema())
        return self._mapping

    @property
    def mapping(self) -> ResolvedMapping:
        if self._mapping is None:
            raise MappingError("call configure() before indexing or searching")
        return self._mapping

    def extractor(self) -> Extractor:
        return Extractor(self.engine, self.mapping, schema=self.db_schema,
                         validator=self.sql_validator)

    def index(
        self,
        batch_size: int = 500,
        *,
        resume: bool = False,
        prune: bool = True,
        progress: Callable[[IndexStats], None] | None = None,
    ) -> IndexStats:
        """(Re-)index the configured entity. Idempotent; see :mod:`relvector.indexing`."""
        return Indexer(self.extractor(), self.provider, self.store).run(
            batch_size, resume=resume, prune=prune, progress=progress)

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        filters: Mapping[str, Any] | None = None,
        entity: str | None = None,
    ) -> list[SearchResult]:
        """Nearest records by cosine similarity. Similarity is not evidence of causation.

        ``filters`` match stored metadata exactly, e.g. ``{"orders.status": "delayed"}``.
        ``entity`` defaults to the configured mapping's entity, if any.
        """
        if entity is None and self._mapping is not None:
            entity = self._mapping.entity
        vector = self.provider.embed([query])
        return self.store.search(vector[0], top_k, entity=entity, filters=filters)
