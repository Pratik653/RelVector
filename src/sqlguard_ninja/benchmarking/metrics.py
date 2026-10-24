"""Detection metrics with explicit definitions.

Positive class: a case whose expected outcome is *not* ALLOW (``deny`` or ``review``), i.e.
something that must not run unattended. A prediction is positive when the validator's decision
is not ALLOW. On top of the binary view, ``exact_match_rate`` measures how often the
three-way decision (allow/review/deny) matches exactly.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlguard_ninja.core.findings import Decision


@dataclass(frozen=True)
class CaseOutcome:
    id: str
    category: str
    dialect: str
    provenance: str
    expected: Decision
    actual: Decision
    latency_ms: float
    error: str | None = None
    in_capability: bool = True

    @property
    def unsafe(self) -> bool:
        return self.expected is not Decision.ALLOW

    @property
    def flagged(self) -> bool:
        return self.actual is not Decision.ALLOW

    @property
    def kind(self) -> str:
        if self.unsafe and self.flagged:
            return "tp"
        if self.unsafe:
            return "fn"
        if self.flagged:
            return "fp"
        return "tn"


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (deterministic, no interpolation)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return round(ordered[rank - 1], 4)


def summarise(outcomes: Iterable[CaseOutcome]) -> dict[str, Any]:
    items = list(outcomes)
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for o in items:
        counts[o.kind] += 1
    tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]
    latencies = [o.latency_ms for o in items]
    return {
        "cases": len(items),
        "unsafe_cases": tp + fn,
        "safe_cases": tn + fp,
        **counts,
        "recall": _ratio(tp, tp + fn),
        "precision": _ratio(tp, tp + fp),
        "false_positive_rate": _ratio(fp, fp + tn),
        "false_negative_rate": _ratio(fn, fn + tp),
        "exact_match_rate": _ratio(sum(o.expected is o.actual for o in items), len(items)),
        "errors": sum(o.error is not None for o in items),
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
            "max": round(max(latencies), 4) if latencies else None,
        },
    }


def grouped(outcomes: list[CaseOutcome], attr: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[CaseOutcome]] = defaultdict(list)
    for o in outcomes:
        key = getattr(o, attr)
        if attr == "provenance":
            key = key.split(":")[0] if not key.startswith("generated:") else key.split("@")[0]
        groups[key].append(o)
    return {k: summarise(v) for k, v in sorted(groups.items())}


def compute_metrics(outcomes: list[CaseOutcome], examples: int = 15) -> dict[str, Any]:
    capable = [o for o in outcomes if o.in_capability]
    return {
        "overall": summarise(outcomes),
        "within_capability": summarise(capable),
        "by_category": grouped(outcomes, "category"),
        "by_dialect": grouped(outcomes, "dialect"),
        "by_provenance": grouped(outcomes, "provenance"),
        "false_negative_examples": [o.id for o in outcomes if o.kind == "fn"][:examples],
        "false_positive_examples": [o.id for o in outcomes if o.kind == "fp"][:examples],
        "decision_mismatch_examples": [
            o.id for o in outcomes if o.expected is not o.actual and o.kind in ("tp", "tn")
        ][:examples],
    }
