"""Starter files written by ``sqlninja init``."""

from __future__ import annotations

from sqlguard_ninja.cli.config import DEFAULT_CONFIG

POLICY = """\
# Starter policy. Labels are assigned explicitly by you; nothing is inferred from names.
version: 1
name: starter
dialect: postgres
labels:
  contact: {sensitivity: high, masking: return the email domain}
  financial: {sensitivity: high, masking: aggregate}
catalog:
  default_schema: public
  tables:
    customers:
      tenant_column: tenant_id
      columns:
        id: int
        tenant_id: int
        name: text
        email: {labels: [contact], alternatives: [email_domain]}
        email_domain: text
    orders:
      tenant_column: tenant_id
      columns:
        id: int
        tenant_id: int
        customer_id: int
        status: text
        total: {type: numeric, labels: [financial]}
roles:
  support:
    tables: {customers: "*", orders: "*"}
    labels: {contact: allow, financial: aggregate_only}
tenant:
  context_key: tenant_id
  parameter_names: [tenant_id]
"""

MANIFEST = """\
name: my-sql-policy-tests
version: "0.1.0"
policy: ../../policies/policy.yaml
default_context: {tenant_id: 1}
case_files: [cases/*.yaml]
"""

CASES = """\
defaults:
  role: support
  dialects: [postgres]
cases:
  - id: OK-001
    sql: SELECT o.id, o.status FROM orders o WHERE o.tenant_id = 1
    category: legitimate_complex
    expected: allow
    explanation: Tenant-pinned order lookup.
  - id: TEN-001
    sql: SELECT o.id FROM orders o
    category: tenant_isolation
    expected: deny
    reason: tenant_isolation
    explanation: Missing tenant filter.
  - id: PRV-001
    sql: SELECT o.total FROM orders o WHERE o.tenant_id = 1
    category: sensitive_field
    expected: deny
    reason: aggregate_only
    explanation: Individual order totals are aggregate-only.
  - id: PRV-002
    sql: SELECT SUM(o.total) FROM orders o WHERE o.tenant_id = 1
    category: sensitive_field
    expected: allow
    explanation: Aggregated totals are permitted.
  - id: DES-001
    sql: DELETE FROM orders WHERE tenant_id = 1
    category: destructive
    expected: deny
    reason: write_statement
    explanation: Writes are never allowed.
"""

FILES = {
    "sqlninja.yaml": DEFAULT_CONFIG,
    "policies/policy.yaml": POLICY,
    "benchmarks/cases/manifest.yaml": MANIFEST,
    "benchmarks/cases/cases/examples.yaml": CASES,
}
