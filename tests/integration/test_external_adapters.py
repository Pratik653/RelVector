"""Run the real external validators through their isolated workers.

Skipped unless ``scripts/setup_external_adapters.py`` has created the environments.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sqlguard_ninja.benchmarking.adapters import EXTERNAL_TOOLS, SubprocessAdapter
from sqlguard_ninja.benchmarking.dataset import load_dataset
from sqlguard_ninja.core.findings import Decision
from tests.conftest import DATASET_PATH, ROOT

DS = load_dataset(DATASET_PATH)
BIN = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"


@pytest.mark.parametrize("name", sorted(EXTERNAL_TOOLS))
def test_external_worker_runs(name):
    py = ROOT / ".venvs" / name / BIN
    if not Path(py).exists():
        pytest.skip(f"{name} environment not set up")
    adapter = SubprocessAdapter(EXTERNAL_TOOLS[name], py, DS.policy)
    try:
        drop = next(c for c in DS.cases if c.id == "DES-001@postgres")
        ok = next(c for c in DS.cases if c.id == "TEN-014@postgres")
        assert adapter.evaluate(drop).decision is Decision.DENY
        verdict = adapter.evaluate(ok)
        assert verdict.error is None
        assert adapter.version not in ("", "unknown")
    finally:
        adapter.close()
