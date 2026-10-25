"""Bounded, read-only extraction of root rows and their related rows.

* Root rows are read in primary-key order with keyset pagination (``WHERE pk > :last``), never
  ``OFFSET``, so each batch costs an index range scan regardless of how deep the run is.
* Related rows are fetched per batch with ``IN (...)`` on the join key: one query per relation,
  no joins, so a one-to-many relation can never multiply root rows (no Cartesian products).
* One-to-many relations are capped per parent with ``ROW_NUMBER()`` in the database and the true
  total is counted separately, so memory is bounded by ``batch_size * max_items`` and any
  truncation is reported rather than silent.

Incremental sync (:mod:`relvector.sync`) adds keyset scans of changed rows in
``(tracking_column, primary key)`` order, bounded by ``LIMIT``, and look-ups of root rows by
primary key or join key, also in bounded batches.

Only ``SELECT`` statements built with SQLAlchemy Core are executed; all values are bound
parameters. Identifiers come from the inspected schema, not from free-form user SQL.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, column, func, select, table, tuple_
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import TableClause

from relvector.mapping import Relation, ResolvedMapping

SqlValidator = Callable[[str], None]
"""Called with each extraction query (named bind parameters) before it runs; raise to block."""

Row = Mapping[str, Any]


@dataclass(frozen=True)
class RowBundle:
    row: Row
    related: dict[str, tuple[list[Row], int]]


@dataclass(frozen=True)
class Batch:
    bundles: list[RowBundle]
    last_key: list[Any]


class Extractor:
    def __init__(
        self,
        engine: Engine,
        resolved: ResolvedMapping,
        *,
        schema: str | None = None,
        validator: SqlValidator | None = None,
    ) -> None:
        self.engine = engine
        self.resolved = resolved
        self.schema = schema
        self.validator = validator

    def _table(self, name: str, columns: Sequence[str]) -> TableClause:
        return table(name, *(column(c) for c in columns), schema=self.schema)

    def _execute(self, conn: Connection, stmt: Select[Any]) -> list[Row]:
        if self.validator is not None:
            self.validator(self.render(stmt))
        return [dict(r) for r in conn.execute(stmt).mappings()]

    def render(self, stmt: Select[Any]) -> str:
        """The statement as SQL text with named parameters (what a validator sees)."""
        dialect = type(self.engine.dialect)(paramstyle="named")  # type: ignore[call-arg]
        return str(stmt.compile(dialect=dialect, compile_kwargs={"render_postcompile": True}))

    def root_query(self, batch_size: int, after: Sequence[Any] | None) -> Select[Any]:
        r = self.resolved
        t = self._table(r.root_table, r.root_select_columns)
        pk = [t.c[c] for c in r.primary_key]
        # SQLite permits NULL in non-INTEGER primary keys; such rows have no stable identity.
        stmt = (select(*(t.c[c] for c in r.root_select_columns))
                .where(*(c.is_not(None) for c in pk), *self._live())
                .order_by(*pk).limit(batch_size))
        if after is not None:
            if len(pk) == 1:
                stmt = stmt.where(pk[0] > after[0])
            else:
                stmt = stmt.where(tuple_(*pk) > tuple_(*after))
        return stmt

    def _live(self) -> list[ColumnElement[bool]]:
        """Filter out soft-deleted root rows (when a ``soft_delete`` column is configured)."""
        sd = self.resolved.soft_delete
        return [] if sd is None else [column(sd).is_(None)]

    def _bundles(self, conn: Connection, rows: list[Row]) -> list[RowBundle]:
        related = {rel.table: self._fetch_related(conn, rel, rows)
                   for rel in self.resolved.relations}
        return [
            RowBundle(row, {t: per_key.get(row[rel.root_column], ([], 0))
                            for t, (rel, per_key) in related.items()})
            for row in rows
        ]

    def iter_batches(
        self, batch_size: int = 500, after: Sequence[Any] | None = None
    ) -> Iterator[Batch]:
        """Yield batches of at most ``batch_size`` root rows, resuming after key ``after``."""
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        last = list(after) if after is not None else None
        while True:
            with self.engine.connect() as conn:
                rows = self._execute(conn, self.root_query(batch_size, last))
                if not rows:
                    return
                bundles = self._bundles(conn, rows)
            last = [rows[-1][c] for c in self.resolved.primary_key]
            yield Batch(bundles, last)
            if len(rows) < batch_size:
                return

    # --- incremental sync -----------------------------------------------------------------

    def _pk_filter(self, t: TableClause, pk: Sequence[str],
                   keys: Sequence[Sequence[Any]]) -> ColumnElement[bool]:
        if len(pk) == 1:
            return t.c[pk[0]].in_([k[0] for k in keys])
        return tuple_(*(t.c[c] for c in pk)).in_([tuple(k) for k in keys])

    def fetch_roots(self, keys: Sequence[Sequence[Any]]) -> list[RowBundle]:
        """Current, not soft-deleted root rows with these primary keys, with related rows."""
        if not keys:
            return []
        r = self.resolved
        t = self._table(r.root_table, r.root_select_columns)
        stmt = (select(*(t.c[c] for c in r.root_select_columns))
                .where(self._pk_filter(t, r.primary_key, keys), *self._live())
                .order_by(*(t.c[c] for c in r.primary_key)))
        with self.engine.connect() as conn:
            rows = self._execute(conn, stmt)
            return self._bundles(conn, rows) if rows else []

    def max_value(self, table_name: str, column_name: str) -> Any:
        """``MAX(column)`` of a table (``None`` when it has no non-NULL values)."""
        t = self._table(table_name, [column_name])
        with self.engine.connect() as conn:
            rows = self._execute(conn, select(func.max(t.c[column_name]).label("_rv_max")))
        return rows[0]["_rv_max"] if rows else None

    def iter_changed(
        self, table_name: str, tracking: str, pk: Sequence[str], extra: Sequence[str],
        low: Any, high: Any, batch_size: int,
    ) -> Iterator[list[Row]]:
        """Rows with ``low <= tracking <= high`` in ``(tracking, pk)`` keyset order.

        ``low=None`` means no lower bound. Rows whose tracking value is NULL are never returned.
        Each yielded list holds at most ``batch_size`` rows (``tracking``, ``pk``, ``extra``).
        """
        cols = list(dict.fromkeys((tracking, *pk, *extra)))
        t = self._table(table_name, cols)
        order = [t.c[tracking], *(t.c[c] for c in pk)]
        base = select(*(t.c[c] for c in cols)).where(
            t.c[tracking].is_not(None), t.c[tracking] <= high,
            *(t.c[c].is_not(None) for c in pk))
        if low is not None:
            base = base.where(t.c[tracking] >= low)
        base = base.order_by(*order).limit(batch_size)
        last: list[Any] | None = None
        while True:
            stmt = base if last is None else base.where(tuple_(*order) > tuple_(*last))
            with self.engine.connect() as conn:
                rows = self._execute(conn, stmt)
            if not rows:
                return
            yield rows
            if len(rows) < batch_size:
                return
            last = [rows[-1][tracking], *(rows[-1][c] for c in pk)]

    def iter_root_keys(self, column_name: str, values: Sequence[Any],
                       batch_size: int) -> Iterator[list[tuple[Any, ...]]]:
        """Primary keys of root rows whose ``column_name`` is in ``values``, in pk order.

        Soft-deleted rows are included: their records must be removed. Batched by keyset.
        """
        r = self.resolved
        vals = sorted({v for v in values if v is not None}, key=lambda k: (str(type(k)), k))
        if not vals:
            return
        t = self._table(r.root_table, list(dict.fromkeys((*r.primary_key, column_name))))
        pk = [t.c[c] for c in r.primary_key]
        base = (select(*pk).where(t.c[column_name].in_(vals), *(c.is_not(None) for c in pk))
                .order_by(*pk).limit(batch_size))
        last: list[Any] | None = None
        while True:
            stmt = base
            if last is not None:
                stmt = (base.where(pk[0] > last[0]) if len(pk) == 1
                        else base.where(tuple_(*pk) > tuple_(*last)))
            with self.engine.connect() as conn:
                rows = self._execute(conn, stmt)
            if not rows:
                return
            keys = [tuple(row[c] for c in r.primary_key) for row in rows]
            yield keys
            if len(rows) < batch_size:
                return
            last = list(keys[-1])

    def _fetch_related(
        self, conn: Connection, rel: Relation, rows: list[Row]
    ) -> tuple[Relation, dict[Any, tuple[list[Row], int]]]:
        keys = sorted({r[rel.root_column] for r in rows if r[rel.root_column] is not None},
                      key=lambda k: (str(type(k)), k))
        if not keys:
            return rel, {}
        t = self._table(rel.table, rel.select_columns)
        join_col = t.c[rel.related_column]
        cols = [t.c[c] for c in rel.select_columns]
        out: dict[Any, tuple[list[Row], int]] = {}
        if rel.kind == "many_to_one":
            for r in self._execute(conn, select(*cols).where(join_col.in_(keys))):
                out[r[rel.related_column]] = ([r], 1)
            return rel, out

        rn = func.row_number().over(
            partition_by=join_col, order_by=[t.c[c] for c in rel.primary_key]
        ).label("_rv_rn")
        ranked = select(*cols, rn).where(join_col.in_(keys)).subquery()
        capped = (select(*(ranked.c[c] for c in rel.select_columns))
                  .where(ranked.c["_rv_rn"] <= rel.max_items)
                  .order_by(ranked.c[rel.related_column], ranked.c["_rv_rn"]))
        counts = select(join_col, func.count().label("_rv_n")).where(
            join_col.in_(keys)).group_by(join_col)
        totals = {r[rel.related_column]: r["_rv_n"] for r in self._execute(conn, counts)}
        grouped: dict[Any, list[Row]] = {}
        for r in self._execute(conn, capped):
            grouped.setdefault(r[rel.related_column], []).append(r)
        for key, total in totals.items():
            out[key] = (grouped.get(key, []), total)
        return rel, out
