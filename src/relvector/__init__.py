"""RelVector — schema-aware semantic indexes over existing relational databases.

RelVector does not turn a SQL database into a vector database. It builds and maintains a
semantic index over *selected* relational data, keeping source references back to the rows;
the original database remains the authoritative source and is only ever read.
"""

from relvector._version import __version__
from relvector.api import RelVector, connect
from relvector.embeddings import EmbeddingProvider, HashingEmbedding, SentenceTransformerEmbedding
from relvector.errors import (
    IndexMismatchError,
    MappingError,
    QueryRejectedError,
    RelVectorError,
    RunSupersededError,
    SchemaError,
    SensitiveFieldError,
)
from relvector.indexing import IndexStats
from relvector.mapping import EntityMapping, Include, SemanticRecord
from relvector.schema import Schema, inspect_schema
from relvector.store import LocalVectorStore, SearchResult, VectorStore

__all__ = [
    "EmbeddingProvider",
    "EntityMapping",
    "HashingEmbedding",
    "Include",
    "IndexMismatchError",
    "IndexStats",
    "LocalVectorStore",
    "MappingError",
    "QueryRejectedError",
    "RelVector",
    "RelVectorError",
    "RunSupersededError",
    "Schema",
    "SchemaError",
    "SearchResult",
    "SemanticRecord",
    "SensitiveFieldError",
    "SentenceTransformerEmbedding",
    "VectorStore",
    "__version__",
    "connect",
    "inspect_schema",
]
