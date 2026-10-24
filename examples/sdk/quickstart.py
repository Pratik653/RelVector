"""Direct Python SDK usage: validate SQL against a policy for a role and tenant.

Run:  python examples/sdk/quickstart.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _shared import load_policy

from sqlguard_ninja import Guard

policy = load_policy()
guard = Guard(policy)

queries = [
    ("support_analyst", "SELECT o.id, o.status FROM orders o WHERE o.tenant_id = :tenant_id"),
    ("support_analyst", "SELECT p.card_number FROM payments p WHERE p.tenant_id = 1"),
    ("support_analyst", "SELECT o.id FROM orders o WHERE o.tenant_id = 1 OR 1 = 1"),
    ("hr_analyst", "SELECT department, AVG(salary) FROM employees GROUP BY department"),
    ("hr_analyst", "SELECT full_name, salary FROM employees"),
    ("platform_admin", "SELECT p.iban FROM payments p WHERE p.tenant_id = 1"),
]

for role, sql in queries:
    result = guard.validate(sql, role=role, context={"tenant_id": 1})
    print(f"\n[{role}] {sql}")
    print(result.explain())
