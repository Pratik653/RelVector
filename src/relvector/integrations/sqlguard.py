"""Optional SQLGuard Ninja integration: validate every extraction query against a policy.

``pip install sqlguard-ninja``. Only the public API (``Guard.validate``) is used. A denial (or
an approval that requires human review) blocks extraction with :class:`QueryRejectedError`.

SQLGuard approval means the *query* is permitted for the role; it is not permission to embed
and store the returned values. Sensitive-field authorisation remains the mapping's job
(``exclude_fields`` / ``allow_sensitive``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from relvector.errors import QueryRejectedError


class SQLGuardValidator:
    """Callable for ``RelVector(sql_validator=...)``."""

    def __init__(self, guard: Any, *, role: str | None = None, dialect: str | None = None,
                 context: Mapping[str, Any] | None = None) -> None:
        self.guard = guard
        self.role = role
        self.dialect = dialect
        self.context = dict(context or {})

    def __call__(self, sql: str) -> None:
        result = self.guard.validate(sql, role=self.role, dialect=self.dialect,
                                     context=self.context)
        if not result.allowed:
            raise QueryRejectedError(f"SQLGuard blocked an extraction query: {result.explain()}")
