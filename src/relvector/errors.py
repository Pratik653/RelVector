"""Exception hierarchy: every error RelVector raises on purpose is a :class:`RelVectorError`."""

from __future__ import annotations


class RelVectorError(Exception):
    """Base class for RelVector errors."""


class SchemaError(RelVectorError):
    """A table, column or relationship does not exist or cannot be resolved."""


class MappingError(RelVectorError):
    """An entity mapping is invalid (unknown field, ambiguous join, conflicting options)."""


class SensitiveFieldError(MappingError):
    """A mapping would embed or store a column that looks sensitive and was not authorised."""


class IndexMismatchError(RelVectorError):
    """A persisted index was built with a different embedding model or dimension."""


class RunSupersededError(RelVectorError):
    """Another indexing run for the same entity started; this run stopped without pruning."""


class QueryRejectedError(RelVectorError):
    """An optional SQL validator (for example SQLGuard Ninja) rejected an extraction query."""
