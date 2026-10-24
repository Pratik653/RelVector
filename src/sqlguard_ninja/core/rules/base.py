"""Rule protocol and the context passed to every rule."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlguard_ninja.core.analysis import QueryAnalysis
from sqlguard_ninja.core.findings import Finding
from sqlguard_ninja.policy.model import Disclosure, Limits, Policy, Role


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule may look at. Rules must not mutate it."""

    analysis: QueryAnalysis
    policy: Policy
    role_name: str | None
    role: Role | None
    limits: Limits
    context: Mapping[str, Any] = field(default_factory=dict)
    """Trusted, server-side request values (e.g. ``tenant_id``). Never model output."""

    def name(self, kind: str, value: str) -> str:
        """Render a schema object name subject to the policy's disclosure setting."""
        if self.policy.disclosure == Disclosure.GENERIC:
            return f"requested {kind}"
        return f"{kind} '{value}'"


@runtime_checkable
class Rule(Protocol):
    """A policy rule. ``rule_ids`` documents every id the rule can emit."""

    @property
    def rule_ids(self) -> tuple[str, ...]: ...

    def check(self, ctx: RuleContext) -> Iterable[Finding]: ...
