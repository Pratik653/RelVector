"""Mechanics of the function policy, using fictitious policy-configured function names."""

from __future__ import annotations

from sqlguard_ninja import Guard, Policy

BASE = {
    "name": "fn",
    "dialect": "postgres",
    "catalog": {"tables": {"t": {"columns": {"id": "int", "name": "text"}}}},
}


def _rules(functions: dict, sql: str) -> tuple[str, set[str]]:
    g = Guard(Policy.from_dict({**BASE, "functions": functions}))
    r = g.validate(sql)
    return r.decision.value, {f.rule_id for f in r.findings}


def test_policy_deny_list_extends_builtins():
    d, rules = _rules({"deny": ["acme_export"]}, "SELECT acme_export(t.id) FROM t")
    assert d == "deny" and "function.denied" in rules


def test_policy_review_list():
    d, rules = _rules({"review": ["acme_lookup"]}, "SELECT acme_lookup(t.id) FROM t")
    assert d == "review" and "function.review" in rules


def test_unknown_function_default_warns_only():
    d, rules = _rules({}, "SELECT acme_format(t.name) FROM t")
    assert d == "allow" and "function.unknown" in rules


def test_unknown_function_action_configurable():
    d, _ = _rules({"unknown_function_action": "deny"}, "SELECT acme_format(t.name) FROM t")
    assert d == "deny"


def test_allowlist_mode_permits_only_listed():
    fns = {"mode": "allowlist", "allow": ["upper", "count"]}
    assert _rules(fns, "SELECT UPPER(t.name), COUNT(*) FROM t GROUP BY t.name")[0] == "allow"
    d, rules = _rules(fns, "SELECT LOWER(t.name) FROM t")
    assert d == "deny" and "function.not_allowlisted" in rules


def test_allowlist_applies_to_nested_calls():
    fns = {"mode": "allowlist", "allow": ["upper"]}
    d, rules = _rules(fns, "SELECT UPPER(acme_format(t.name)) FROM t")
    assert d == "deny" and "function.not_allowlisted" in rules


def test_denylist_exception_overrides_policy_review():
    fns = {"review": ["acme_lookup"], "allow": ["acme_lookup"]}
    assert _rules(fns, "SELECT acme_lookup(t.id) FROM t")[0] == "allow"


def test_function_names_are_case_insensitive():
    d, _ = _rules({"deny": ["acme_export"]}, "SELECT ACME_Export(t.id) FROM t")
    assert d == "deny"


def test_function_in_where_and_subquery_is_seen():
    fns = {"deny": ["acme_export"]}
    assert _rules(fns, "SELECT t.id FROM t WHERE acme_export(t.id) > 0")[0] == "deny"
    assert _rules(fns, "SELECT t.id FROM t WHERE t.id IN (SELECT acme_export(1))")[0] == "deny"


def test_generic_disclosure_hides_function_names():
    g = Guard(
        Policy.from_dict({**BASE, "functions": {"deny": ["acme_export"]}, "disclosure": "generic"})
    )
    r = g.validate("SELECT acme_export(t.id) FROM t")
    assert all("acme_export" not in f.message for f in r.findings)
