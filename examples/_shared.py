"""Shared helpers for the examples: locate the benchmark policy and build a demo database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlguard_ninja import Policy
from sqlguard_ninja.benchmarking.fixtures import create_sqlite

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "benchmarks" / "policies" / "retail_saas.yaml"


def load_policy() -> Policy:
    return Policy.from_file(POLICY_PATH)


def demo_database(policy: Policy) -> sqlite3.Connection:
    """In-memory SQLite database with synthetic data (no real personal data)."""
    return create_sqlite(policy)
