"""Entity mappings: which relational data becomes one semantic record, and how it is worded.

A mapping names a root table (one semantic record per root row), directly related tables,
and the exact columns that may be embedded (``text_fields``) or stored alongside the vector
(``metadata_fields``). Columns that are not listed are never selected from the database.

Text is produced by deterministic templates, never by a language model, so the same rows and
the same mapping always produce byte-identical text and the same content hash.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from relvector.errors import MappingError, SensitiveFieldError
from relvector.schema import Schema, TableInfo

NULL_TEXT = "not recorded"

# Adapted from sqlguard_ninja.privacy.suggest (Apache-2.0, same authors). Name heuristics are
# unreliable, so they only *block* by default; a data owner authorises via ``allow_sensitive``.
_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("payment_card", re.compile(r"(card_?(number|no|num)|\bpan\b|cc_?num|cvv)")),
    ("financial", re.compile(r"(iban|bank|account_?number|salary|wage|income)")),
    ("government_id", re.compile(r"(ssn|national_?id|passport|tax_?id|\bnin\b)")),
    ("contact", re.compile(r"(e_?mail|phone|mobile|address|postcode|zip)")),
    ("personal_identifier", re.compile(r"(full_?name|first_?name|last_?name|birth|\bdob\b)")),
    ("special_category", re.compile(r"(health|medical|diagnos|religio|ethnic|biometric)")),
    ("credentials", re.compile(r"(password|passwd|secret|token|api_?key)")),
]


def sensitive_label(column: str) -> str | None:
    """Return a sensitivity label if the column *name* looks sensitive, else ``None``."""
    name = column.lower()
    for label, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(name):
            return label
    return None


@dataclass(frozen=True)
class Include:
    """A table directly related to the root table.

    ``via`` makes the join explicit as ``("root.col", "related.col")``; without it the single
    declared foreign key between the two tables is used.
    """

    table: str
    via: tuple[str, str] | None = None
    max_items: int | None = None


@dataclass(frozen=True)
class EntityMapping:
    root_table: str
    text_fields: Sequence[str]
    include: Sequence[str | Include] = ()
    metadata_fields: Sequence[str] = ()
    exclude_fields: Sequence[str] = ()
    allow_sensitive: Sequence[str] = ()
    templates: Mapping[str, str] = field(default_factory=dict)
    labels: Mapping[str, str] = field(default_factory=dict)
    name: str | None = None
    version: str = "1"
    max_children: int = 20
    # Opt-in incremental sync (see :mod:`relvector.sync`). ``change_tracking`` maps each mapped
    # table to a column the application reliably bumps on every insert and update (e.g.
    # ``updated_at`` or a version counter). ``soft_delete`` names a root column that is set
    # (non-NULL) when a row is logically deleted; such rows are not indexed. Neither option
    # changes documents of indexed rows, so neither is part of the mapping fingerprint.
    change_tracking: Mapping[str, str] = field(default_factory=dict)
    soft_delete: str | None = None

    @property
    def entity(self) -> str:
        return self.name or self.root_table


@dataclass(frozen=True)
class Relation:
    table: str
    kind: Literal["many_to_one", "one_to_many"]
    root_column: str
    related_column: str
    primary_key: tuple[str, ...]
    text_columns: tuple[str, ...]
    metadata_columns: tuple[str, ...]
    max_items: int

    @property
    def select_columns(self) -> tuple[str, ...]:
        return _unique((self.related_column, *self.primary_key, *self.text_columns,
                        *self.metadata_columns))


@dataclass(frozen=True)
class ResolvedMapping:
    """A mapping validated against a concrete schema."""

    spec: EntityMapping
    primary_key: tuple[str, ...]
    text_columns: tuple[str, ...]
    metadata_columns: tuple[str, ...]
    relations: tuple[Relation, ...]
    fingerprint: str
    # Validated change-tracking columns ``{table: column}`` (possibly partial) and the root
    # soft-delete column. Not part of ``fingerprint``: they never change a document.
    tracking: Mapping[str, str] = field(default_factory=dict)
    soft_delete: str | None = None
    # Declared types of the root primary-key columns (used to re-type stored JSON keys).
    primary_key_types: tuple[str, ...] = ()

    @property
    def entity(self) -> str:
        return self.spec.entity

    @property
    def tables(self) -> tuple[str, ...]:
        """The root table followed by every included table."""
        return (self.root_table, *(r.table for r in self.relations))

    @property
    def untracked_tables(self) -> tuple[str, ...]:
        return tuple(t for t in self.tables if t not in self.tracking)

    @property
    def root_table(self) -> str:
        return self.spec.root_table

    @property
    def root_select_columns(self) -> tuple[str, ...]:
        return _unique((*self.primary_key, *self.text_columns, *self.metadata_columns,
                        *(r.root_column for r in self.relations)))


@dataclass(frozen=True)
class SemanticRecord:
    vector_id: str
    entity: str
    source_table: str
    source_pk: dict[str, Any]
    text: str
    metadata: dict[str, Any]
    references: list[dict[str, Any]]
    truncated: dict[str, int]
    mapping_version: str
    content_hash: str


def _unique(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _split(ref: str, root: str) -> tuple[str, str]:
    if "." in ref:
        table, _, column = ref.partition(".")
        if not table or not column or "." in column:
            raise MappingError(f"field {ref!r} must be 'table.column'")
        return table, column
    return root, ref


def resolve(spec: EntityMapping, schema: Schema) -> ResolvedMapping:
    """Validate ``spec`` against ``schema``. Raises :class:`MappingError` with a clear reason."""
    if not spec.text_fields:
        raise MappingError("text_fields must name at least one column to embed")
    if spec.max_children < 1:
        raise MappingError("max_children must be >= 1")
    root = schema.table(spec.root_table)
    if not root.primary_key:
        raise MappingError(f"root table {root.name!r} has no primary key; a stable identity "
                           "is required for idempotent indexing")

    includes = [Include(i) if isinstance(i, str) else i for i in spec.include]
    tables = {root.name: root}
    for inc in includes:
        if inc.table == root.name:
            raise MappingError("self-referencing includes are not supported in this version")
        if inc.table in tables:
            raise MappingError(f"table {inc.table!r} is included more than once")
        tables[inc.table] = schema.table(inc.table)

    excluded = {_split(f, root.name) for f in spec.exclude_fields}
    allowed_sensitive = {_split(f, root.name) for f in spec.allow_sensitive}

    def fields(refs: Sequence[str], kind: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {t: [] for t in tables}
        for ref in refs:
            table, column = _split(ref, root.name)
            if table not in tables:
                raise MappingError(f"{kind} field {ref!r} uses table {table!r}, which is neither "
                                   "the root table nor an included table")
            tables[table].column(column)
            if (table, column) in excluded:
                raise MappingError(f"{kind} field {table}.{column} is also in exclude_fields")
            label = sensitive_label(column)
            if label and (table, column) not in allowed_sensitive:
                raise SensitiveFieldError(
                    f"{kind} field {table}.{column} looks sensitive ({label}); exclude it or "
                    "list it in allow_sensitive after confirming it may be embedded and stored"
                )
            if column not in out[table]:
                out[table].append(column)
        return out

    text = fields(spec.text_fields, "text")
    meta = fields(spec.metadata_fields, "metadata")

    for tname, template in spec.templates.items():
        if tname not in tables:
            raise MappingError(f"template given for table {tname!r}, which is not mapped")
        allowed = {*text[tname], *tables[tname].primary_key}
        for name in _template_fields(template):
            if name not in allowed:
                raise MappingError(f"template for {tname!r} uses {{{name}}}; templates may only "
                                   "use that table's text_fields and primary key")

    relations = tuple(
        _resolve_relation(inc, root, tables[inc.table], schema, text[inc.table],
                          meta[inc.table], spec.max_children)
        for inc in includes
    )
    resolved_payload = {
        "entity": spec.entity, "root": root.name, "version": spec.version,
        "text": text, "meta": meta, "templates": dict(sorted(spec.templates.items())),
        "labels": dict(sorted(spec.labels.items())),
        "relations": [r.__dict__ for r in relations],
    }
    fingerprint = hashlib.sha256(
        json.dumps(resolved_payload, sort_keys=True, default=list).encode()
    ).hexdigest()[:16]

    def check_aux(table: str, column: str, kind: str) -> None:
        tables[table].column(column)
        if (table, column) in excluded:
            raise MappingError(f"{kind} column {table}.{column} is also in exclude_fields")
        label = sensitive_label(column)
        if label and (table, column) not in allowed_sensitive:
            raise SensitiveFieldError(
                f"{kind} column {table}.{column} looks sensitive ({label}); its values are "
                "read and kept in the index checkpoint, so list it in allow_sensitive to use it"
            )

    tracking: dict[str, str] = {}
    for tname, tcol in spec.change_tracking.items():
        if tname not in tables:
            raise MappingError(f"change_tracking names table {tname!r}, which is neither the "
                               "root table nor an included table")
        if not isinstance(tcol, str) or not tcol or "." in tcol:
            raise MappingError(f"change_tracking for {tname!r} must be a plain column name, "
                               f"got {tcol!r}")
        check_aux(tname, tcol, "change-tracking")
        tracking[tname] = tcol
    if spec.soft_delete is not None:
        sd_table, sd_col = _split(spec.soft_delete, root.name)
        if sd_table != root.name:
            raise MappingError("soft_delete must be a column of the root table "
                               f"{root.name!r}, got {spec.soft_delete!r}")
        check_aux(sd_table, sd_col, "soft-delete")
    return ResolvedMapping(
        spec=spec,
        primary_key=root.primary_key,
        text_columns=tuple(text[root.name]),
        metadata_columns=tuple(meta[root.name]),
        relations=relations,
        fingerprint=fingerprint,
        tracking={t: tracking[t] for t in tables if t in tracking},
        soft_delete=None if spec.soft_delete is None else _split(spec.soft_delete, root.name)[1],
        primary_key_types=tuple(root.column(c).type for c in root.primary_key),
    )


def _resolve_relation(
    inc: Include, root: TableInfo, related: TableInfo, schema: Schema,
    text: list[str], meta: list[str], default_max: int,
) -> Relation:
    if inc.via is not None:
        (lt, lc), (rt, rc) = (_split(inc.via[0], root.name), _split(inc.via[1], related.name))
        if lt != root.name or rt != related.name:
            raise MappingError(f"via for {related.name!r} must be ('{root.name}.col', "
                               f"'{related.name}.col'), got {inc.via!r}")
        root.column(lc)
        related.column(rc)
        root_col, rel_col = lc, rc
        kind: Literal["many_to_one", "one_to_many"] = (
            "many_to_one" if related.primary_key == (rc,) else "one_to_many"
        )
    else:
        fks = [fk for fk in schema.relationships_between(root.name, related.name)
               if not fk.composite]
        if not fks:
            raise MappingError(
                f"no single-column foreign key links {root.name!r} and {related.name!r}; "
                "declare one in the database or pass Include(..., via=(root_col, related_col))"
            )
        if len(fks) > 1:
            listed = "; ".join(str(fk) for fk in fks)
            raise MappingError(f"ambiguous relationship between {root.name!r} and "
                               f"{related.name!r} ({listed}); pass Include(..., via=...)")
        fk = fks[0]
        if fk.table == root.name:
            kind, root_col, rel_col = "many_to_one", fk.columns[0], fk.ref_columns[0]
        else:
            kind, root_col, rel_col = "one_to_many", fk.ref_columns[0], fk.columns[0]
    if not related.primary_key:
        raise MappingError(f"included table {related.name!r} has no primary key; it is needed "
                           "for deterministic ordering and source references")
    if not text and not meta:
        raise MappingError(f"included table {related.name!r} contributes no text or metadata "
                           "fields")
    max_items = inc.max_items if inc.max_items is not None else default_max
    if max_items < 1:
        raise MappingError("max_items must be >= 1")
    return Relation(
        table=related.name, kind=kind, root_column=root_col, related_column=rel_col,
        primary_key=related.primary_key, text_columns=tuple(text),
        metadata_columns=tuple(meta), max_items=max_items,
    )


# --- deterministic serialisation ------------------------------------------------------------


def _template_fields(template: str) -> list[str]:
    names: list[str] = []
    for _, name, spec, conv in string.Formatter().parse(template):
        if name is None:
            continue
        if not name.isidentifier() or spec or conv:
            raise MappingError(f"template placeholder {{{name}}} must be a plain column name "
                               "(no attributes, indexes, conversions or format specs)")
        names.append(name)
    return names


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value  # NaN is not valid JSON
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, _dt.date | _dt.time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(bytes(value))} bytes>"
    return str(value)


def _text(value: Any) -> str:
    if value is None:
        return NULL_TEXT
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, bytes | bytearray | memoryview):
        return "[binary value omitted]"
    return " ".join(str(jsonable(value)).split())


def _humanize(column: str) -> str:
    return column.replace("_", " ").strip().capitalize()


def _singular(table: str) -> str:
    word = table.replace("_", " ")
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word.capitalize()


def _key_text(row: Mapping[str, Any], pk: Sequence[str]) -> str:
    return "/".join(_text(row[c]) for c in pk)


def _render(row: Mapping[str, Any], table: str, pk: Sequence[str], columns: Sequence[str],
            spec: EntityMapping) -> str:
    template = spec.templates.get(table)
    if template is not None:
        names = _template_fields(template)
        # A null would make a template read as a false statement; fall back to explicit text.
        if all(row[n] is not None for n in names):
            return " ".join(template.format(**{n: _text(row[n]) for n in names}).split())
    label = spec.labels.get(table, _singular(table))
    parts = [f"{label} {_key_text(row, pk)}."]
    parts.extend(f"{_humanize(c)}: {_text(row[c])}." for c in columns)
    return " ".join(parts)


def record_id(resolved: ResolvedMapping, pk_values: Sequence[Any]) -> str:
    """The deterministic vector id of the root row with primary-key values ``pk_values``."""
    return f"{resolved.entity}:" + json.dumps([jsonable(v) for v in pk_values],
                                              separators=(",", ":"))


def build_record(
    resolved: ResolvedMapping,
    row: Mapping[str, Any],
    related: Mapping[str, tuple[list[Mapping[str, Any]], int]],
) -> SemanticRecord:
    """Serialise one root row plus its related rows. ``related[table] = (rows, total_count)``."""
    spec = resolved.spec
    pk = {c: jsonable(row[c]) for c in resolved.primary_key}
    sentences = [_render(row, spec.root_table, resolved.primary_key,
                         resolved.text_columns, spec)]
    metadata: dict[str, Any] = {f"{spec.root_table}.{c}": jsonable(row[c])
                                for c in resolved.metadata_columns}
    references: list[dict[str, Any]] = []
    truncated: dict[str, int] = {}

    for rel in resolved.relations:
        rows, total = related.get(rel.table, ([], 0))
        noun = spec.labels.get(rel.table, _singular(rel.table)).lower()
        if rel.kind == "many_to_one":
            if not rows:
                key = row[rel.root_column]
                sentences.append(f"No related {noun} is recorded." if key is None else
                                 f"Related {noun} {_text(key)} was not found.")
            for r in rows:
                sentences.append(_render(r, rel.table, rel.primary_key, rel.text_columns, spec))
        else:
            plural = rel.table.replace("_", " ")
            if total == 0:
                sentences.append(f"No related {plural}.")
            elif total > len(rows):
                sentences.append(f"Related {plural}: {total} in total, showing the first "
                                 f"{len(rows)}.")
                truncated[rel.table] = total - len(rows)
            sentences.extend(_render(r, rel.table, rel.primary_key, rel.text_columns, spec)
                             for r in rows)
        for c in rel.metadata_columns:
            values = [jsonable(r[c]) for r in rows]
            metadata[f"{rel.table}.{c}"] = (values[0] if values else None) \
                if rel.kind == "many_to_one" else values
        references.extend(
            {"table": rel.table, "relation": rel.kind,
             "pk": {c: jsonable(r[c]) for c in rel.primary_key}}
            for r in rows
        )

    text = " ".join(sentences)
    vector_id = record_id(resolved, [row[c] for c in resolved.primary_key])
    content_hash = hashlib.sha256(json.dumps(
        {"text": text, "metadata": metadata, "refs": references, "truncated": truncated,
         "mapping": resolved.fingerprint},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return SemanticRecord(
        vector_id=vector_id, entity=spec.entity, source_table=spec.root_table, source_pk=pk,
        text=text, metadata=metadata, references=references, truncated=truncated,
        mapping_version=spec.version, content_hash=content_hash,
    )
