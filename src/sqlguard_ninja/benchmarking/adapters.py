"""Benchmark adapters: a uniform interface over different SQL validators.

* :class:`NativeAdapter`      — SQLGuard Ninja's own :class:`~sqlguard_ninja.Guard`.
* :class:`CallableAdapter`    — any user function ``module:function``.
* :class:`SubprocessAdapter`  — a worker script run by *another* Python interpreter
  (one virtual environment per external tool), speaking JSON Lines over stdin/stdout.
  This isolates tools whose dependencies or import names conflict.

An adapter declares the case categories its policy model can express (``capabilities``).
Reports show metrics on all cases and on the capability subset, so a tool is not
penalised in a headline number for features it never claimed.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlguard_ninja._version import __version__
from sqlguard_ninja.benchmarking.dataset import BenchmarkCase
from sqlguard_ninja.benchmarking.translate import translate_for_role
from sqlguard_ninja.core.findings import Decision
from sqlguard_ninja.core.guard import Guard
from sqlguard_ninja.policy.model import Policy

WORKERS_DIR = Path(__file__).parent / "workers"

ALL_CATEGORIES: frozenset[str] | None = None
"""Sentinel: the adapter claims every category."""


@dataclass(frozen=True)
class AdapterVerdict:
    decision: Decision
    reasons: tuple[str, ...] = ()
    latency_ms: float = 0.0
    error: str | None = None
    """Set when the validator crashed; the decision is then DENY (fail closed) and the
    error is counted separately in reports."""


class BenchmarkAdapter(Protocol):
    name: str

    @property
    def version(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str] | None: ...

    def evaluate(self, case: BenchmarkCase) -> AdapterVerdict: ...

    def close(self) -> None: ...


class NativeAdapter:
    """Evaluate cases with SQLGuard Ninja's built-in guard."""

    name = "native"

    def __init__(self, policy: Policy, guard: Guard | None = None) -> None:
        self.guard = guard or Guard(policy)

    @property
    def version(self) -> str:
        return __version__

    @property
    def capabilities(self) -> frozenset[str] | None:
        return ALL_CATEGORIES

    def evaluate(self, case: BenchmarkCase) -> AdapterVerdict:
        started = time.perf_counter()
        result = self.guard.validate(
            case.sql, role=case.role, dialect=case.dialect, context=case.context
        )
        elapsed = (time.perf_counter() - started) * 1000
        reasons = tuple(f.rule_id for f in result.blocking_findings)
        return AdapterVerdict(result.decision, reasons, elapsed)

    def close(self) -> None:
        return None


def _coerce_decision(value: Any) -> tuple[Decision, tuple[str, ...]]:
    """Normalise the many result shapes a user validator may return."""
    reasons: tuple[str, ...] = ()
    if isinstance(value, tuple) and len(value) == 2:
        value, raw = value
        reasons = tuple(str(r) for r in (raw or ()))
    if isinstance(value, dict):
        reasons = tuple(str(r) for r in value.get("reasons", ()))
        value = value.get("decision", value.get("allowed"))
    if isinstance(value, Decision):
        return value, reasons
    if isinstance(value, bool):
        return (Decision.ALLOW if value else Decision.DENY), reasons
    if isinstance(value, str) and value.lower() in {d.value for d in Decision}:
        return Decision(value.lower()), reasons
    raise TypeError(f"cannot interpret validator result {value!r}")


class CallableAdapter:
    """Wrap a Python callable ``fn(sql, dialect, case) -> bool | str | dict | Decision``."""

    def __init__(
        self,
        fn: Callable[[str, str, BenchmarkCase], Any],
        name: str = "callable",
        version: str = "unknown",
        capabilities: frozenset[str] | None = ALL_CATEGORIES,
    ) -> None:
        self.fn = fn
        self.name = name
        self._version = version
        self._capabilities = capabilities

    @classmethod
    def from_spec(cls, spec: str) -> CallableAdapter:
        """Load ``package.module:function``."""
        module_name, _, attr = spec.partition(":")
        if not module_name or not attr:
            raise ValueError("callable adapter spec must look like 'module:function'")
        fn = getattr(importlib.import_module(module_name), attr)
        return cls(fn, name=f"callable:{spec}")

    @property
    def version(self) -> str:
        return self._version

    @property
    def capabilities(self) -> frozenset[str] | None:
        return self._capabilities

    def evaluate(self, case: BenchmarkCase) -> AdapterVerdict:
        started = time.perf_counter()
        try:
            raw = self.fn(case.sql, case.dialect, case)
            decision, reasons = _coerce_decision(raw)
            error = None
        except Exception as exc:  # a crashing validator must not crash the benchmark
            decision, reasons, error = Decision.DENY, (), f"{type(exc).__name__}: {exc}"
        return AdapterVerdict(decision, reasons, (time.perf_counter() - started) * 1000, error)

    def close(self) -> None:
        return None


@dataclass
class ExternalToolSpec:
    """Metadata for a bundled external worker."""

    name: str
    worker: str
    package: str
    pip_spec: str
    capabilities: frozenset[str]
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_BASE_CAPS = frozenset(
    {
        "destructive",
        "multi_statement",
        "comments_formatting",
        "unauthorized_table",
        "unauthorized_column",
        "lookalike_safe",
        "legitimate_complex",
        "cte_bypass",
        "nested_query",
        "join_subquery_policy",
        "unicode_identifiers",
    }
)

EXTERNAL_TOOLS: dict[str, ExternalToolSpec] = {
    "sql-guardrail": ExternalToolSpec(
        name="sql-guardrail",
        worker="sql_guardrail_worker.py",
        package="sql-guardrail",
        pip_spec="sql-guardrail==0.5.2",
        capabilities=_BASE_CAPS | {"tenant_isolation", "cost"},
        notes="Column allow/deny lists and require_predicate; no roles, labels or review.",
    ),
    "agent-sql-guard": ExternalToolSpec(
        name="agent-sql-guard",
        worker="agent_sql_guard_worker.py",
        package="agent-sql-guard",
        pip_spec="agent-sql-guard==0.2.0",
        capabilities=_BASE_CAPS | {"sensitive_field"},
        notes="Table allowlist and a name-based PII denylist; no tenant predicates.",
    ),
    "krish2105-sqlguard": ExternalToolSpec(
        name="krish2105-sqlguard",
        worker="krish_sqlguard_worker.py",
        package="sqlguard",
        pip_spec="sqlguard @ git+https://github.com/krish2105/sqlguard@62327f214ed8c9ea82ecf820bf04c4b55a6161a2",
        capabilities=_BASE_CAPS,
        notes="Read-only AST check with a schema allow-list; not published on PyPI.",
    ),
}


class SubprocessAdapter:
    """Run an external validator in its own interpreter via a JSON Lines worker.

    The worker receives one request per line::

        {"id": ..., "sql": ..., "dialect": ..., "context": {...}, "config": {...}}

    and answers with ``{"decision": "allow|deny|review", "reasons": [...],
    "latency_ms": float, "error": str|null}``. Its first line is a hello message carrying
    ``{"library": ..., "version": ...}``.
    """

    def __init__(
        self,
        tool: ExternalToolSpec,
        python: str | Path,
        policy: Policy,
        timeout_s: float = 30.0,
    ) -> None:
        self.tool = tool
        self.name = tool.name
        self.policy = policy
        self.timeout_s = timeout_s
        worker = WORKERS_DIR / tool.worker
        # -I: isolated mode, so the worker cannot import from the current directory.
        self._proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [str(python), "-I", str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        hello = self._read()
        if "error" in hello and hello.get("error"):
            self.close()
            raise RuntimeError(f"{tool.name} worker failed to start: {hello['error']}")
        self._version = str(hello.get("version", "unknown"))
        self._configs: dict[tuple[str | None, str], dict[str, Any]] = {}

    def _read(self) -> dict[str, Any]:
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            raise RuntimeError(f"{self.tool.name} worker exited: {stderr[-500:]}")
        data: dict[str, Any] = json.loads(line)
        return data

    @property
    def version(self) -> str:
        return self._version

    @property
    def capabilities(self) -> frozenset[str] | None:
        return self.tool.capabilities

    def evaluate(self, case: BenchmarkCase) -> AdapterVerdict:
        key = (case.role, case.dialect)
        if key not in self._configs:
            self._configs[key] = translate_for_role(self.policy, case.role, case.dialect)
        request = {
            "id": case.id,
            "sql": case.sql,
            "dialect": case.dialect,
            "context": case.context,
            "config": self._configs[key],
        }
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(request) + "\n")
        self._proc.stdin.flush()
        reply = self._read()
        decision = Decision(reply.get("decision", "deny"))
        return AdapterVerdict(
            decision=decision,
            reasons=tuple(reply.get("reasons", ())),
            latency_ms=float(reply.get("latency_ms", 0.0)),
            error=reply.get("error"),
        )

    def close(self) -> None:
        if self._proc.poll() is None:
            if self._proc.stdin:
                self._proc.stdin.close()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        for stream in (self._proc.stdout, self._proc.stderr):
            if stream:
                stream.close()
