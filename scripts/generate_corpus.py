"""Generate the deterministic, matrix-style part of the benchmark corpus.

Usage::

    python scripts/generate_corpus.py           # (re)write benchmarks/datasets/v1/generated/
    python scripts/generate_corpus.py --check   # exit 1 if the committed files are stale

The generator reads the policy *YAML* directly with PyYAML and applies the documented policy
semantics itself (see docs/guides/BENCHMARK_METHODOLOGY.md). It does not import the engine,
so engine regressions show up as failures instead of being copied into the labels.

Three families are generated:

* ``grant_matrix``   — every role x every table: is the table readable at all?
* ``label_matrix``   — every role x every classified column it can see: allow / aggregate /
  review / deny, plus a statistical-aggregate variant for aggregate-only columns.
* ``tenant_matrix``  — every tenant-scoped table x ten predicate patterns.
* ``transform``      — semantics-preserving rewrites (comments, whitespace, case, parentheses,
  derived-table and CTE wrapping) of a fixed set of safe and unsafe base queries.

Generation is fully enumerative; ``SEED`` is recorded for provenance only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "policies" / "retail_saas.yaml"
OUT = ROOT / "benchmarks" / "datasets" / "v1" / "generated"
SEED = 20261024
BOTH = ["postgres", "sqlite"]
TENANT = 1
OTHER_TENANT = 3


def _load_policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def _grant_columns(role: dict[str, Any], table: str) -> list[str] | str | None:
    grants = role.get("tables", {})
    if table not in grants:
        return None
    g = grants[table]
    if g == "*" or g is None:
        return "*"
    if isinstance(g, list):
        return g
    return g.get("columns", "*")


def _column_labels(spec: Any) -> list[str]:
    if isinstance(spec, list):
        return spec
    if isinstance(spec, dict):
        labels = list(spec.get("labels", []))
        for field_labels in spec.get("json_fields", {}).values():
            labels.extend(field_labels)
        return labels
    return []


def _case(**kw: Any) -> dict[str, Any]:
    kw.setdefault("dialects", BOTH)
    if kw["expected"] == "allow":
        kw["reason"] = "none"
    return kw


# ----------------------------------------------------------------------------- grant matrix
def grant_matrix(policy: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    tables = policy["catalog"]["tables"]
    for rname, role in policy["roles"].items():
        tenant_scoped = role.get("tenant_scoped", True)
        for tname, tdef in tables.items():
            grant = _grant_columns(role, tname)
            col = "id"
            pin = ""
            if tdef.get("tenant_column") and tenant_scoped:
                pin = f" WHERE t.{tdef['tenant_column']} = {TENANT}"
            sql = f"SELECT t.{col} FROM {tname} t{pin} LIMIT 100"
            granted = grant is not None and (grant == "*" or col in grant)
            cases.append(
                _case(
                    id=f"GEN-GRANT-{rname}-{tname}",
                    role=rname,
                    sql=sql,
                    category="unauthorized_table",
                    expected="allow" if granted else "deny",
                    reason="unauthorized_table",
                    classification=None if granted else "policy_violation",
                    provenance=f"generated:grant_matrix@{SEED}",
                    explanation=f"Role {rname} {'has' if granted else 'has no'} grant on {tname}.",
                )
            )
    return cases


# ----------------------------------------------------------------------------- label matrix
def _label_outcome(role: dict[str, Any], labels: list[str]) -> tuple[str, bool]:
    """Return (strongest restriction, any_review) under the documented semantics."""
    default = role.get("unlisted_label_access", "deny")
    accesses = [role.get("labels", {}).get(lbl, default) for lbl in labels]
    if "deny" in accesses:
        return "deny", False
    review = "review" in accesses
    if "aggregate_only" in accesses:
        return "aggregate_only", review
    if review:
        return "review", True
    return "allow", False


def label_matrix(policy: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    tables = policy["catalog"]["tables"]
    for rname, role in policy["roles"].items():
        tenant_scoped = role.get("tenant_scoped", True)
        for tname, tdef in tables.items():
            grant = _grant_columns(role, tname)
            if grant is None:
                continue
            pin = ""
            if tdef.get("tenant_column") and tenant_scoped:
                pin = f" WHERE t.{tdef['tenant_column']} = {TENANT}"
            for cname, spec in tdef["columns"].items():
                labels = _column_labels(spec)
                if not labels:
                    continue
                base = {
                    "role": rname,
                    "category": "sensitive_field",
                    "provenance": f"generated:label_matrix@{SEED}",
                }
                sql = f"SELECT t.{cname} FROM {tname} t{pin} LIMIT 100"
                if grant != "*" and cname not in grant:
                    cases.append(
                        _case(
                            id=f"GEN-LABEL-{rname}-{tname}-{cname}",
                            sql=sql,
                            expected="deny",
                            reason="unauthorized_column",
                            classification="policy_violation",
                            explanation=f"{tname}.{cname} is outside {rname}'s column grant.",
                            **base,
                        )
                    )
                    continue
                outcome, review = _label_outcome(role, sorted(set(labels)))
                expected = {
                    "deny": "deny",
                    "aggregate_only": "deny",
                    "review": "review",
                    "allow": "allow",
                }[outcome]
                reason = {
                    "deny": "sensitive_data",
                    "aggregate_only": "aggregate_only",
                    "review": "sensitive_data",
                    "allow": "none",
                }[outcome]
                cases.append(
                    _case(
                        id=f"GEN-LABEL-{rname}-{tname}-{cname}",
                        sql=sql,
                        expected=expected,
                        reason=reason,
                        classification=None,
                        explanation=f"Labels {sorted(set(labels))} resolve to '{outcome}' "
                        f"for {rname}; the column is projected individually.",
                        **base,
                    )
                )
                if outcome == "aggregate_only":
                    agg_sql = f"SELECT COUNT(DISTINCT t.{cname}) FROM {tname} t{pin}"
                    cases.append(
                        _case(
                            id=f"GEN-LABEL-{rname}-{tname}-{cname}-agg",
                            sql=agg_sql,
                            expected="review" if review else "allow",
                            reason="sensitive_data",
                            classification=None,
                            explanation="A statistical aggregate satisfies aggregate-only access.",
                            **base,
                        )
                    )
    return cases


# ---------------------------------------------------------------------------- tenant matrix
TENANT_PATTERNS: list[tuple[str, str, str, list[str]]] = [
    # (key, WHERE/suffix template, expected, dialects)
    ("missing", "", "deny", BOTH),
    ("wrong", "WHERE t.tenant_id = {other}", "deny", BOTH),
    ("or_bypass", "WHERE t.tenant_id = {tenant} OR t.id > 0", "deny", BOTH),
    ("in_multi", "WHERE t.tenant_id IN ({tenant}, {other})", "deny", BOTH),
    ("range", "WHERE t.tenant_id > 0", "deny", BOTH),
    ("pinned", "WHERE t.tenant_id = {tenant}", "allow", BOTH),
    ("pinned_reversed", "WHERE {tenant} = t.tenant_id", "allow", BOTH),
    ("pinned_param", "WHERE t.tenant_id = :tenant_id", "allow", ["postgres"]),
    (
        "outer_unpinned",
        "WHERE t.id IN (SELECT x.id FROM {table} x WHERE x.tenant_id = {tenant})",
        "deny",
        BOTH,
    ),
    (
        "both_pinned",
        "WHERE t.tenant_id = {tenant} AND t.id IN "
        "(SELECT x.id FROM {table} x WHERE x.tenant_id = {tenant})",
        "allow",
        BOTH,
    ),
]


def tenant_matrix(policy: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    role = "support_analyst"
    for tname, tdef in policy["catalog"]["tables"].items():
        if not tdef.get("tenant_column"):
            continue
        if _grant_columns(policy["roles"][role], tname) is None:
            continue
        for key, template, expected, dialects in TENANT_PATTERNS:
            where = template.format(tenant=TENANT, other=OTHER_TENANT, table=tname)
            sql = f"SELECT t.id FROM {tname} t {where}".strip() + " LIMIT 50"
            cases.append(
                _case(
                    id=f"GEN-TENANT-{tname}-{key}",
                    role=role,
                    sql=sql,
                    dialects=dialects,
                    category="tenant_isolation",
                    expected=expected,
                    reason="tenant_isolation",
                    classification=None if expected == "allow" else "policy_violation",
                    provenance=f"generated:tenant_matrix@{SEED}",
                    explanation=f"Tenant pattern '{key}' on {tname}.",
                )
            )
    return cases


# -------------------------------------------------------------------------------- transforms
BASES: list[dict[str, Any]] = [
    {
        "key": "s1",
        "role": "support_analyst",
        "expected": "allow",
        "reason": "none",
        "sql": "SELECT o.id, o.status FROM orders o WHERE o.tenant_id = 1",
    },
    {
        "key": "s2",
        "role": "support_analyst",
        "expected": "allow",
        "reason": "none",
        "sql": "SELECT s.carrier, COUNT(*) AS n FROM shipments s WHERE s.tenant_id = 1 GROUP BY s.carrier",
    },
    {
        "key": "s3",
        "role": "hr_analyst",
        "expected": "allow",
        "reason": "none",
        "sql": "SELECT e.department, AVG(e.salary) AS a FROM employees e GROUP BY e.department",
    },
    {
        "key": "s4",
        "role": "finance_analyst",
        "expected": "allow",
        "reason": "none",
        "sql": "SELECT p.status, SUM(p.amount) AS total FROM payments p WHERE p.tenant_id = 1 GROUP BY p.status",
    },
    {
        "key": "s5",
        "role": "support_analyst",
        "expected": "allow",
        "reason": "none",
        "sql": "SELECT c.id, c.email_domain FROM customers c WHERE c.tenant_id = 1 ORDER BY c.id LIMIT 10",
    },
    {
        "key": "s6",
        "role": "warehouse_analyst",
        "expected": "allow",
        "reason": "none",
        "sql": "SELECT w.region, COUNT(*) AS n FROM shipments s JOIN warehouses w ON w.id = s.warehouse_id WHERE s.tenant_id = 1 GROUP BY w.region",
    },
    {
        "key": "u1",
        "role": "support_analyst",
        "expected": "deny",
        "reason": "sensitive_data",
        "sql": "SELECT p.card_number FROM payments p WHERE p.tenant_id = 1",
    },
    {
        "key": "u2",
        "role": "support_analyst",
        "expected": "deny",
        "reason": "tenant_isolation",
        "sql": "SELECT o.id FROM orders o WHERE o.tenant_id = 2",
    },
    {
        "key": "u3",
        "role": "support_analyst",
        "expected": "deny",
        "reason": "tenant_isolation",
        "sql": "SELECT o.id FROM orders o WHERE o.tenant_id = 1 OR 1 = 1",
    },
    {
        "key": "u4",
        "role": "hr_analyst",
        "expected": "deny",
        "reason": "aggregate_only",
        "sql": "SELECT e.full_name, e.salary FROM employees e WHERE e.id > 0",
    },
    {
        "key": "u5",
        "role": "warehouse_analyst",
        "expected": "deny",
        "reason": "unauthorized_table",
        "sql": "SELECT e.id FROM employees e WHERE e.id > 0",
    },
    {
        "key": "u6",
        "role": "support_analyst",
        "expected": "deny",
        "reason": "write_statement",
        "sql": "DELETE FROM orders WHERE tenant_id = 1",
        "wrappable": False,
    },
    {
        "key": "u7",
        "role": "support_analyst",
        "expected": "deny",
        "reason": "tenant_isolation",
        "sql": "SELECT o.id FROM orders o JOIN shipments s ON s.order_id = o.id WHERE o.tenant_id = 1",
    },
    {
        "key": "u8",
        "role": "support_analyst",
        "expected": "deny",
        "reason": "unauthorized_column",
        "sql": "SELECT c.phone FROM customers c WHERE c.tenant_id = 1",
    },
]

_KEYWORDS = (
    r"\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|JOIN|ON|AND|OR|LIMIT|AS|DELETE|COUNT|SUM|AVG)\b"
)


def _t_comments(sql: str) -> str:
    sql = sql.replace(" FROM ", " /* source */ FROM ", 1)
    return sql.replace(" WHERE ", "\n-- filter follows\nWHERE ", 1)


def _t_whitespace(sql: str) -> str:
    return re.sub(r" ", "\n\t  ", sql)


def _t_lower(sql: str) -> str:
    return re.sub(_KEYWORDS, lambda m: m.group(0).lower(), sql)


def _t_mixed(sql: str) -> str:
    return re.sub(
        _KEYWORDS,
        lambda m: "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(m.group(0))),
        sql,
    )


def _t_paren_where(sql: str) -> str | None:
    m = re.search(r" WHERE (.+?)( GROUP BY | ORDER BY |$)", sql)
    if not m:
        return None
    return sql[: m.start(1)] + "(" + m.group(1) + ")" + sql[m.end(1) :]


def _t_derived(sql: str) -> str:
    return f"SELECT w.* FROM ({sql}) AS w"


def _t_cte(sql: str) -> str:
    return f"WITH w AS ({sql}) SELECT * FROM w"


TRANSFORMS = [
    ("comments", _t_comments, True),
    ("whitespace", _t_whitespace, True),
    ("lowercase", _t_lower, True),
    ("mixedcase", _t_mixed, True),
    ("paren_where", _t_paren_where, True),
    ("derived", _t_derived, False),
    ("cte", _t_cte, False),
]


def transforms() -> list[dict[str, Any]]:
    cases = []
    for base in BASES:
        for tkey, fn, textual in TRANSFORMS:
            if not textual and not base.get("wrappable", True):
                continue
            if tkey == "derived" and " LIMIT " in base["sql"]:
                pass  # ORDER BY/LIMIT inside a derived table is valid in both dialects
            sql = fn(base["sql"])
            if sql is None or sql == base["sql"]:
                continue
            cases.append(
                _case(
                    id=f"GEN-XFORM-{base['key']}-{tkey}",
                    role=base["role"],
                    sql=sql,
                    category="comments_formatting" if textual else "nested_query",
                    expected=base["expected"],
                    reason=base["reason"],
                    classification=None,
                    provenance=f"generated:transform/{tkey}@{SEED}",
                    explanation=f"Semantics-preserving '{tkey}' rewrite of base query "
                    f"{base['key']} ({base['expected']}).",
                )
            )
    return cases


def render() -> dict[str, str]:
    policy = _load_policy()
    families = {
        "grant_matrix.yaml": grant_matrix(policy),
        "label_matrix.yaml": label_matrix(policy),
        "tenant_matrix.yaml": tenant_matrix(policy),
        "transforms.yaml": transforms(),
    }
    out = {}
    for name, cases in families.items():
        for c in cases:
            if c.get("classification") is None:
                c.pop("classification", None)
        header = f"# GENERATED by scripts/generate_corpus.py (seed {SEED}). Do not edit by hand.\n"
        out[name] = header + yaml.safe_dump(
            {"cases": cases}, sort_keys=False, allow_unicode=True, width=120
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if files are out of date")
    args = parser.parse_args(argv)
    rendered = render()
    stale = []
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        path = OUT / name
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != text:
            stale.append(name)
            if not args.check:
                path.write_text(text, encoding="utf-8", newline="\n")
    if args.check and stale:
        print(f"stale generated files: {stale}; run scripts/generate_corpus.py", file=sys.stderr)
        return 1
    total = sum(t.count("\n- id:") + t.startswith("- id:") for t in rendered.values())
    print(f"{'checked' if args.check else 'wrote'} {len(rendered)} files, {total} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
