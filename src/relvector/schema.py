"""Read-only schema inspection through SQLAlchemy's inspector.

Inspection reads catalog metadata only (tables, columns, primary keys, declared foreign keys);
it never reads row data and never issues DDL or DML.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from relvector.errors import SchemaError


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True)
class ForeignKey:
    """``table.columns`` references ``ref_table.ref_columns`` (declared in the database)."""

    table: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]
    name: str | None = None

    @property
    def composite(self) -> bool:
        return len(self.columns) > 1

    def __str__(self) -> str:
        cols = ", ".join(self.columns)
        refs = ", ".join(self.ref_columns)
        return f"{self.table}({cols}) -> {self.ref_table}({refs})"


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKey, ...] = ()

    def column(self, name: str) -> ColumnInfo:
        for col in self.columns:
            if col.name == name:
                return col
        raise SchemaError(f"table {self.name!r} has no column {name!r}")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class Schema:
    tables: dict[str, TableInfo] = field(default_factory=dict)
    schema: str | None = None

    def table(self, name: str) -> TableInfo:
        try:
            return self.tables[name]
        except KeyError:
            known = ", ".join(sorted(self.tables)) or "(none)"
            raise SchemaError(f"unknown table {name!r}; known tables: {known}") from None

    @property
    def foreign_keys(self) -> list[ForeignKey]:
        return [fk for t in self.tables.values() for fk in t.foreign_keys]

    def relationships_between(self, a: str, b: str) -> list[ForeignKey]:
        """Declared foreign keys linking ``a`` and ``b`` in either direction."""
        return [
            fk
            for fk in self.foreign_keys
            if {fk.table, fk.ref_table} == {a, b} or (a == b == fk.table == fk.ref_table)
        ]

    def describe(self) -> str:
        """Compact, human-readable summary (no row data)."""
        lines: list[str] = []
        for t in sorted(self.tables.values(), key=lambda t: t.name):
            cols = ", ".join(
                f"{c.name}:{c.type}{'*' if c.primary_key else ''}" for c in t.columns
            )
            lines.append(f"{t.name} ({cols})")
            lines.extend(f"  FK {fk}" for fk in t.foreign_keys)
        return "\n".join(lines)


def inspect_schema(
    engine: Engine, *, schema: str | None = None, tables: Iterable[str] | None = None
) -> Schema:
    """Inspect tables, columns, primary keys and declared foreign keys."""
    insp = inspect(engine)
    names = list(tables) if tables is not None else insp.get_table_names(schema=schema)
    out: dict[str, TableInfo] = {}
    for name in names:
        pk = tuple(insp.get_pk_constraint(name, schema=schema).get("constrained_columns") or ())
        cols = tuple(
            ColumnInfo(
                name=c["name"],
                type=str(c["type"]),
                nullable=bool(c.get("nullable", True)),
                primary_key=c["name"] in pk,
            )
            for c in insp.get_columns(name, schema=schema)
        )
        fks = tuple(
            ForeignKey(
                table=name,
                columns=tuple(fk["constrained_columns"]),
                ref_table=fk["referred_table"],
                ref_columns=tuple(fk["referred_columns"]),
                name=fk.get("name"),
            )
            for fk in insp.get_foreign_keys(name, schema=schema)
            if fk.get("referred_table")
        )
        out[name] = TableInfo(name=name, columns=cols, primary_key=pk, foreign_keys=fks)
    return Schema(tables=out, schema=schema)
