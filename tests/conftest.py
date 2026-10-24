from __future__ import annotations

from pathlib import Path

import pytest

from sqlguard_ninja import Guard, Policy

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "benchmarks" / "policies" / "retail_saas.yaml"
DATASET_PATH = ROOT / "benchmarks" / "datasets" / "v1"


@pytest.fixture(scope="session")
def policy() -> Policy:
    return Policy.from_file(POLICY_PATH)


@pytest.fixture(scope="session")
def guard(policy: Policy) -> Guard:
    return Guard(policy)


@pytest.fixture
def check(guard: Guard):
    """Validate as a role with tenant 1 and return (decision, rule ids)."""

    def _check(sql: str, role: str = "support_analyst", dialect: str = "postgres", **ctx):
        context = {"tenant_id": 1, **ctx}
        result = guard.validate(sql, role=role, dialect=dialect, context=context)
        return result.decision.value, {f.rule_id for f in result.findings}

    return _check
