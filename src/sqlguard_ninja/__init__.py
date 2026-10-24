"""SQLGuard Ninja — policy enforcement, agent checkpoints and benchmarking for LLM-generated SQL.

Static SQL inspection is one layer of defence. It does not replace database permissions,
row-level security, statement timeouts or authentication.
"""

from sqlguard_ninja._version import __version__
from sqlguard_ninja.core.findings import (
    Action,
    Category,
    Decision,
    Finding,
    Severity,
    ValidationResult,
)
from sqlguard_ninja.core.guard import Guard, default_rules
from sqlguard_ninja.core.rules.base import Rule, RuleContext
from sqlguard_ninja.policy.model import Access, Policy, PolicyError

__all__ = [
    "Access",
    "Action",
    "Category",
    "Decision",
    "Finding",
    "Guard",
    "Policy",
    "PolicyError",
    "Rule",
    "RuleContext",
    "Severity",
    "ValidationResult",
    "__version__",
    "default_rules",
]
