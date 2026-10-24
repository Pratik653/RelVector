from __future__ import annotations

import json

import pytest

from sqlguard_ninja import Policy, PolicyError
from sqlguard_ninja.policy import Access, ColumnDef

MINIMAL = {
    "name": "mini",
    "catalog": {"tables": {"orders": {"columns": {"id": "int", "status": "text"}}}},
}


def test_minimal_policy_loads():
    p = Policy.from_dict(MINIMAL)
    assert p.version == 1
    assert p.catalog.tables["orders"].columns["id"].type == "int"


def test_names_are_lowercased():
    p = Policy.from_dict(
        {"name": "x", "catalog": {"tables": {"Orders": {"columns": {"ID": "int"}}}}}
    )
    assert "orders" in p.catalog.tables
    assert "id" in p.catalog.tables["orders"].columns


def test_unknown_label_rejected():
    data = {
        "name": "x",
        "catalog": {"tables": {"t": {"columns": {"email": ["contact"]}}}},
    }
    with pytest.raises(PolicyError, match="unknown label 'contact'"):
        Policy.from_dict(data)


def test_grant_on_unknown_table_rejected():
    data = {**MINIMAL, "roles": {"r": {"tables": {"nope": "*"}}}}
    with pytest.raises(PolicyError, match="unknown table 'nope'"):
        Policy.from_dict(data)


def test_grant_on_unknown_column_rejected():
    data = {**MINIMAL, "roles": {"r": {"tables": {"orders": ["id", "missing"]}}}}
    with pytest.raises(PolicyError, match=r"orders\.missing"):
        Policy.from_dict(data)


def test_tenant_column_must_exist():
    data = {
        "name": "x",
        "catalog": {"tables": {"t": {"tenant_column": "tid", "columns": {"id": "int"}}}},
    }
    with pytest.raises(PolicyError, match="tenant_column"):
        Policy.from_dict(data)


def test_unknown_alternative_rejected():
    data = {
        "name": "x",
        "catalog": {"tables": {"t": {"columns": {"a": {"alternatives": ["b"]}}}}},
    }
    with pytest.raises(PolicyError, match="alternative 'b'"):
        Policy.from_dict(data)


def test_unknown_default_role_rejected():
    with pytest.raises(PolicyError, match="default_role"):
        Policy.from_dict({**MINIMAL, "default_role": "ghost"})


def test_cost_threshold_order_validated():
    with pytest.raises(PolicyError, match="review_score"):
        Policy.from_dict({**MINIMAL, "cost": {"review_score": 90, "deny_score": 10}})


def test_extra_keys_forbidden():
    with pytest.raises(PolicyError):
        Policy.from_dict({**MINIMAL, "surprise": True})


def test_json_and_yaml_files(tmp_path):
    j = tmp_path / "p.json"
    j.write_text(json.dumps(MINIMAL))
    assert Policy.from_file(j).name == "mini"
    y = tmp_path / "p.yaml"
    y.write_text("name: mini\ncatalog: {tables: {t: {columns: {id: int}}}}\n")
    assert "t" in Policy.from_file(y).catalog.tables


def test_non_mapping_file_rejected(tmp_path):
    y = tmp_path / "p.yaml"
    y.write_text("- just\n- a list\n")
    with pytest.raises(PolicyError, match="mapping"):
        Policy.from_file(y)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(PolicyError, match="cannot read"):
        Policy.from_file(tmp_path / "missing.yaml")


def test_role_shorthand_and_default_role(policy):
    grant = policy.roles["support_analyst"].tables["orders"]
    assert grant.columns == "*"
    assert policy.roles["hr_analyst"].labels["financial"] is Access.AGGREGATE_ONLY
    p = Policy.from_dict(
        {**MINIMAL, "roles": {"r": {"tables": {"orders": "*"}}}, "default_role": "r"}
    )
    assert p.role(None)[0] == "r"


def test_json_field_effective_labels():
    col = ColumnDef(json_fields={"a.b": ["x"], "a.c": ["y"], "d": ["z"]})
    assert col.effective_labels() == {"x", "y", "z"}
    assert col.effective_labels(("a",)) == {"x", "y"}  # descendants revealed
    assert col.effective_labels(("a", "b")) == {"x"}
    assert col.effective_labels(("a", "b", "deep")) == {"x"}  # ancestor label applies
    assert col.effective_labels(("q",)) == set()


def test_benchmark_policy_is_valid(policy):
    assert set(policy.roles) >= {"support_analyst", "hr_analyst", "warehouse_analyst"}
