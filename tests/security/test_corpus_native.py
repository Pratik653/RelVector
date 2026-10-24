"""Every benchmark case, evaluated by the native engine, must match its expected outcome.

Cases listed in KNOWN_DIVERGENCES are documented engine limitations: they are marked
xfail(strict=True) so a fix that starts passing them is noticed and the list is updated.
"""

from __future__ import annotations

import pytest

from sqlguard_ninja import Guard
from sqlguard_ninja.benchmarking.dataset import load_dataset
from tests.conftest import DATASET_PATH

DATASET = load_dataset(DATASET_PATH)
GUARD = Guard(DATASET.policy)

KNOWN_DIVERGENCES: dict[str, str] = {}


@pytest.mark.parametrize("case", DATASET.cases, ids=lambda c: c.id)
def test_case(case):
    if case.id in KNOWN_DIVERGENCES:
        pytest.xfail(KNOWN_DIVERGENCES[case.id])
    result = GUARD.validate(case.sql, role=case.role, dialect=case.dialect, context=case.context)
    assert result.decision == case.expected, (
        f"{case.id}: expected {case.expected.value}, got {result.decision.value}\n"
        f"{case.explanation}\n{result.explain(include_detail=True)}"
    )
