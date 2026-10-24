"""Behavioural tests for each built-in rule against the benchmark policy."""

from __future__ import annotations

import pytest

from sqlguard_ninja import Guard, Policy


class TestStatements:
    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE orders",
            "DELETE FROM orders WHERE tenant_id = 1",
            "UPDATE orders SET status = 'x' WHERE tenant_id = 1",
            "INSERT INTO orders (id) VALUES (1)",
            "CREATE TABLE t AS SELECT 1",
        ],
    )
    def test_writes_denied(self, check, sql):
        decision, rules = check(sql)
        assert decision == "deny"
        assert rules & {"statement.not_read_only", "statement.write_in_query"}

    def test_data_modifying_cte(self, check):
        decision, rules = check("WITH d AS (DELETE FROM orders RETURNING id) SELECT id FROM d")
        assert decision == "deny"
        assert "statement.write_in_query" in rules

    def test_select_into(self, check):
        _, rules = check("SELECT id INTO TEMP x FROM orders WHERE tenant_id = 1")
        assert "statement.select_into" in rules

    def test_locking(self, check):
        _, rules = check("SELECT id FROM orders WHERE tenant_id = 1 FOR UPDATE")
        assert "statement.locking" in rules

    def test_command_fallback(self, check):
        decision, rules = check("VACUUM FULL orders")
        assert decision == "deny"
        assert "statement.unsupported" in rules

    def test_multiple_statements(self, check):
        decision, rules = check("SELECT 1; SELECT 2")
        assert decision == "deny"
        assert rules == {"statement.multiple"}

    def test_trailing_semicolon_is_one_statement(self, check):
        assert check("SELECT id FROM orders WHERE tenant_id = 1;")[0] == "allow"

    def test_mysql_executable_comment(self):
        policy = Policy.from_dict(
            {
                "name": "m",
                "dialect": "mysql",
                "catalog": {"tables": {"t": {"columns": {"id": "int"}}}},
            }
        )
        r = Guard(policy).validate("SELECT id FROM t /*!50000 , x */")
        assert "statement.executable_comment" in {f.rule_id for f in r.findings}


class TestParse:
    @pytest.mark.parametrize("sql", ["", "   ", "-- nothing"])
    def test_empty(self, check, sql):
        decision, rules = check(sql)
        assert decision == "deny"
        assert "parse.empty" in rules

    def test_parse_error(self, check):
        decision, rules = check("SELEC id FROM")
        assert decision == "deny"
        assert rules & {"parse.error", "statement.unsupported"}

    def test_too_long(self, guard):
        r = guard.validate("SELECT 1 " + " " * 30000, role="support_analyst")
        assert {f.rule_id for f in r.findings} == {"parse.too_long"}

    def test_lone_surrogate_rejected_not_raised(self, check):
        # Regression: found by Hypothesis; validate() raised UnicodeEncodeError.
        assert check("SELECT 1 /*\ud800*/")[1] == {"parse.invalid_characters"}

    def test_nul_byte(self, check):
        assert "parse.invalid_characters" in check("SELECT 1\x00")[1]

    def test_too_complex(self, policy):
        tight = policy.model_copy(
            update={"limits": policy.limits.model_copy(update={"max_ast_nodes": 5})}
        )
        r = Guard(tight).validate(
            "SELECT id, status, total_amount FROM orders WHERE tenant_id = 1", role="platform_admin"
        )
        assert "parse.too_complex" in {f.rule_id for f in r.findings}


class TestRoles:
    def test_missing_role_denied(self, guard):
        r = guard.validate("SELECT 1")
        assert r.denied and r.findings[0].rule_id == "role.unknown"

    def test_undefined_role_denied(self, guard):
        assert guard.validate("SELECT 1", role="ghost").denied

    def test_policy_without_roles_uses_implicit_role(self):
        p = Policy.from_dict(
            {
                "name": "n",
                "labels": {"contact": {}},
                "catalog": {"tables": {"t": {"columns": {"id": "int", "email": ["contact"]}}}},
            }
        )
        g = Guard(p)
        assert g.validate("SELECT id FROM t").allowed
        assert g.validate("SELECT email FROM t").denied


class TestTableAndColumnAccess:
    def test_ungranted_table(self, check):
        decision, rules = check("SELECT e.id FROM employees e", role="warehouse_analyst")
        assert decision == "deny"
        assert "table.not_permitted" in rules

    def test_unknown_and_ungranted_share_message(self, guard):
        a = guard.validate("SELECT 1 FROM secrets", role="warehouse_analyst")
        b = guard.validate("SELECT 1 FROM employees", role="warehouse_analyst")
        msg = lambda r: next(f.message for f in r.findings if f.rule_id == "table.not_permitted")  # noqa: E731
        assert msg(a).replace("secrets", "X") == msg(b).replace("employees", "X")

    def test_other_schema_denied(self, check):
        assert check("SELECT id FROM private.orders WHERE tenant_id = 1")[0] == "deny"

    def test_default_schema_allowed(self, check):
        assert check("SELECT o.id FROM public.orders o WHERE o.tenant_id = 1")[0] == "allow"

    def test_ungranted_column(self, check):
        decision, rules = check("SELECT phone FROM customers WHERE tenant_id = 1")
        assert decision == "deny"
        assert "column.not_permitted" in rules

    def test_column_not_in_catalog(self, check):
        decision, _rules = check("SELECT password FROM customers WHERE tenant_id = 1")
        assert decision == "deny"

    def test_star_expanded_against_grant(self, check):
        decision, rules = check("SELECT * FROM payments WHERE tenant_id = 1")
        assert decision == "deny"
        assert "column.not_permitted" in rules

    def test_whole_row_reference(self, check):
        assert check("SELECT customers FROM customers WHERE tenant_id = 1")[0] == "deny"

    def test_unexpandable_star(self, check):
        _, rules = check("SELECT * FROM mystery")
        assert "column.star_unexpandable" in rules

    def test_ambiguous_unqualified_column_fails_closed(self, check):
        # 'id' exists on both tables; without a schema hint the qualifier cannot attribute it.
        decision, rules = check(
            "SELECT nonexistent FROM orders o JOIN shipments s ON s.order_id = o.id "
            "WHERE o.tenant_id = 1 AND s.tenant_id = 1"
        )
        assert decision == "deny"
        assert "column.unresolved" in rules

    def test_order_by_select_alias_is_resolved(self, check):
        assert check("SELECT status AS s FROM orders WHERE tenant_id = 1 ORDER BY s")[0] == "allow"

    def test_alias_does_not_launder_column(self, check):
        decision, _ = check(
            "WITH x AS (SELECT p.card_number AS harmless FROM payments p WHERE p.tenant_id = 1) "
            "SELECT harmless FROM x"
        )
        assert decision == "deny"


class TestTenant:
    def test_literal_pin(self, check):
        assert check("SELECT id FROM orders WHERE tenant_id = 1")[0] == "allow"

    def test_parameter_pin(self, check):
        assert check("SELECT id FROM orders WHERE tenant_id = :tenant_id")[0] == "allow"

    def test_wrong_value(self, check):
        assert "tenant.wrong_value" in check("SELECT id FROM orders WHERE tenant_id = 2")[1]

    def test_multi_value_in_list(self, check):
        assert check("SELECT id FROM orders WHERE tenant_id IN (1, 2)")[0] == "deny"

    def test_single_value_in_list(self, check):
        assert check("SELECT id FROM orders WHERE tenant_id IN (1)")[0] == "allow"

    def test_or_bypass(self, check):
        assert (
            "tenant.missing_predicate"
            in check("SELECT id FROM orders WHERE tenant_id = 1 OR 1 = 1")[1]
        )

    def test_missing(self, check):
        assert check("SELECT id FROM orders")[0] == "deny"

    def test_missing_context(self, guard):
        r = guard.validate("SELECT id FROM orders WHERE tenant_id = 1", role="support_analyst")
        assert "tenant.context_missing" in {f.rule_id for f in r.findings}

    def test_equality_chain_through_join(self, check):
        sql = (
            "SELECT o.id, s.status FROM orders o JOIN shipments s "
            "ON s.order_id = o.id AND s.tenant_id = o.tenant_id WHERE o.tenant_id = 1"
        )
        assert check(sql)[0] == "allow"

    def test_join_without_tenant_link(self, check):
        sql = (
            "SELECT o.id FROM orders o JOIN shipments s ON s.order_id = o.id WHERE o.tenant_id = 1"
        )
        assert "tenant.missing_predicate" in check(sql)[1]

    def test_left_join_on_pin(self, check):
        sql = (
            "SELECT o.id, s.status FROM orders o LEFT JOIN shipments s "
            "ON s.order_id = o.id AND s.tenant_id = 1 WHERE o.tenant_id = 1"
        )
        assert check(sql)[0] == "allow"

    def test_left_join_on_does_not_pin_preserved_side(self, check):
        sql = (
            "SELECT o.id FROM orders o LEFT JOIN shipments s "
            "ON s.order_id = o.id AND o.tenant_id = 1 AND s.tenant_id = 1"
        )
        assert check(sql)[0] == "deny"

    def test_subquery_needs_own_pin(self, check):
        sql = "SELECT id FROM orders WHERE tenant_id = 1 AND customer_id IN (SELECT id FROM customers)"
        assert check(sql)[0] == "deny"

    def test_union_arms_each_pinned(self, check):
        ok = "SELECT id FROM orders WHERE tenant_id = 1 UNION SELECT id FROM shipments WHERE tenant_id = 1"
        bad = "SELECT id FROM orders WHERE tenant_id = 1 UNION SELECT id FROM shipments"
        assert check(ok)[0] == "allow"
        assert check(bad)[0] == "deny"

    def test_cast_literal(self, check):
        assert check("SELECT id FROM orders WHERE tenant_id = CAST('1' AS INT)")[0] == "allow"

    def test_non_tenant_role_skips(self, check):
        assert check("SELECT id FROM orders", role="platform_admin")[0] == "allow"


class TestPrivacy:
    def test_aggregate_allowed(self, check):
        sql = "SELECT department, AVG(salary) FROM employees GROUP BY department"
        assert check(sql, role="hr_analyst")[0] == "allow"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT salary FROM employees",
            "SELECT MAX(salary) FROM employees",
            "SELECT SUM(salary) OVER (PARTITION BY id) FROM employees",
            "SELECT id FROM employees WHERE salary > 100000",
            "SELECT id FROM employees ORDER BY salary DESC",
            "SELECT salary, COUNT(*) FROM employees GROUP BY salary",
        ],
    )
    def test_aggregate_only_violations(self, check, sql):
        decision, rules = check(sql, role="hr_analyst")
        assert decision == "deny"
        assert "privacy.aggregate_only" in rules

    def test_small_cohort_review(self, check):
        decision, rules = check("SELECT AVG(salary) FROM employees WHERE id = 5", role="hr_analyst")
        assert decision == "review"
        assert "privacy.small_cohort" in rules

    def test_label_deny(self, check):
        decision, rules = check("SELECT national_id FROM employees", role="hr_analyst")
        assert decision == "deny" and "privacy.label_denied" in rules

    def test_special_category_message(self, guard):
        r = guard.validate("SELECT health_notes FROM employees", role="hr_analyst")
        assert "special-category" in r.findings[0].message

    def test_label_review(self, check):
        decision, rules = check("SELECT iban FROM payments", role="platform_admin")
        assert decision == "review" and "privacy.label_review" in rules

    def test_json_path_allowed_and_denied(self, check):
        ok = "SELECT profile->'preferences'->>'language' FROM customers WHERE tenant_id = 1"
        bad = "SELECT profile->'health'->>'allergies' FROM customers WHERE tenant_id = 1"
        whole = "SELECT profile FROM customers WHERE tenant_id = 1"
        assert check(ok)[0] == "allow"
        assert check(bad)[0] == "deny"
        assert check(whole)[0] == "deny"

    def test_sqlite_json_extract_path(self, check):
        bad = "SELECT json_extract(profile, '$.payment.card_number') FROM customers WHERE tenant_id = 1"
        ok = "SELECT json_extract(profile, '$.preferences.language') FROM customers WHERE tenant_id = 1"
        assert check(bad, dialect="sqlite")[0] == "deny"
        assert check(ok, dialect="sqlite")[0] == "allow"

    def test_alternative_suggested(self, guard):
        r = guard.validate(
            "SELECT card_number FROM payments WHERE tenant_id = 1",
            role="finance_analyst",
            context={"tenant_id": 1},
        )
        assert any(f.remediation and "card_last4" in f.remediation for f in r.findings)

    def test_minimization_warning_does_not_block(self, check):
        decision, rules = check("SELECT c.email FROM customers c WHERE c.tenant_id = 1")
        assert decision == "allow"
        assert "privacy.minimization" in rules

    def test_explicit_column_rule_overrides_label(self, policy):
        data = policy.model_dump(mode="json")
        data["roles"]["hr_analyst"]["tables"]["employees"] = {
            "columns": "*",
            "column_access": {"national_id": "review"},
        }
        g = Guard(Policy.from_dict(data))
        assert g.validate("SELECT national_id FROM employees", role="hr_analyst").requires_review

    def test_generic_disclosure_hides_names(self, policy):
        g = Guard(policy.model_copy(update={"disclosure": "generic"}))
        r = g.validate("SELECT national_id FROM employees", role="hr_analyst")
        assert all("national_id" not in f.message for f in r.findings)


class TestStructureAndCost:
    def test_limit_exceeded(self, check):
        sql = "SELECT id FROM orders WHERE tenant_id = 1 LIMIT 5000"
        assert "structure.limit_exceeded" in check(sql, role="reporting_agent")[1]

    def test_limit_not_numeric(self, check):
        sql = "SELECT id FROM orders WHERE tenant_id = 1 LIMIT ALL"
        assert check(sql, role="reporting_agent")[0] == "deny"

    def test_require_limit(self, policy):
        lim = policy.limits.model_copy(update={"require_limit": True})
        g = Guard(policy.model_copy(update={"limits": lim}))
        r = g.validate("SELECT id FROM warehouses", role="hr_analyst")
        assert "structure.limit_missing" in {f.rule_id for f in r.findings}

    def test_max_joins(self, check):
        joins = " ".join(
            f"JOIN products p{i} ON p{i}.id = o.id AND p{i}.tenant_id = 1" for i in range(5)
        )
        sql = f"SELECT o.id FROM orders o {joins} WHERE o.tenant_id = 1"
        assert "structure.max_joins" in check(sql, role="reporting_agent")[1]

    def test_max_depth(self, check):
        sql = "SELECT id FROM warehouses"
        for _ in range(5):
            sql = f"SELECT id FROM ({sql}) AS s"
        assert "structure.max_depth" in check(sql, role="hr_analyst")[1]

    def test_cartesian_on_large_tables_flagged(self, check):
        sql = "SELECT o.id FROM orders o CROSS JOIN order_items i"
        decision, rules = check(sql, role="platform_admin")
        assert decision in ("review", "deny")
        assert "cost.static_score" in rules

    def test_small_tables_not_flagged(self, check):
        assert check("SELECT w.name FROM warehouses w", role="hr_analyst")[0] == "allow"

    def test_cost_disabled(self, policy):
        g = Guard(
            policy.model_copy(update={"cost": policy.cost.model_copy(update={"enabled": False})})
        )
        r = g.validate("SELECT o.id FROM orders o CROSS JOIN order_items i", role="platform_admin")
        assert "cost.static_score" not in {f.rule_id for f in r.findings}


class TestResult:
    def test_result_fields(self, guard):
        r = guard.validate(
            "SELECT o.id FROM orders o WHERE o.tenant_id = 1",
            role="support_analyst",
            context={"tenant_id": 1},
        )
        assert r.allowed and not r.denied and not r.requires_review
        assert r.tables == ("orders",)
        assert "orders.tenant_id" in r.columns
        assert len(r.sql_sha256) == 64
        assert r.explain().startswith("ALLOW")

    def test_explain_lists_findings(self, guard):
        r = guard.validate("SELECT national_id FROM employees", role="hr_analyst")
        text = r.explain(include_detail=True)
        assert "privacy.label_denied" in text and "restricted by" in text

    def test_custom_rule(self, guard):
        from sqlguard_ninja import Action, Category, Finding, Severity

        class NoStatusRule:
            rule_ids = ("custom.no_status",)

            def check(self, ctx):
                if "status" in {c.column for c in ctx.analysis.columns}:
                    yield Finding(
                        rule_id="custom.no_status",
                        category=Category.STRUCTURE,
                        severity=Severity.LOW,
                        action=Action.REVIEW,
                        message="status",
                    )

        g = guard.with_rules([NoStatusRule()])
        r = g.validate(
            "SELECT status FROM orders WHERE tenant_id = 1",
            role="support_analyst",
            context={"tenant_id": 1},
        )
        assert r.requires_review
