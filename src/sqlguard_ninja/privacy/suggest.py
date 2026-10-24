"""Name-based classification *suggestions* for humans to review.

The guard never uses these heuristics to enforce anything: column names are unreliable
(``notes`` may hold health data, ``email`` may hold a hash). They exist to speed up writing a
first policy, which a data owner must then confirm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlguard_ninja.policy.model import Catalog

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("payment_card", re.compile(r"(card_?(number|no|num)|pan|cc_?num)")),
    ("financial", re.compile(r"(iban|bank|account_?number|salary|wage|income)")),
    ("government_id", re.compile(r"(ssn|national_?id|passport|tax_?id|nin\b)")),
    ("contact", re.compile(r"(e_?mail|phone|mobile|address|postcode|zip)")),
    ("personal_identifier", re.compile(r"(full_?name|first_?name|last_?name|birth|dob)")),
    ("special_category", re.compile(r"(health|medical|diagnos|religio|ethnic|biometric)")),
    ("credentials", re.compile(r"(password|passwd|secret|token|api_?key)")),
]


@dataclass(frozen=True)
class Suggestion:
    table: str
    column: str
    label: str
    matched: str


def suggest_labels(catalog: Catalog) -> list[Suggestion]:
    """Suggest labels for unlabelled columns whose names match common patterns."""
    out: list[Suggestion] = []
    for tname, table in catalog.tables.items():
        for cname, col in table.columns.items():
            if col.labels:
                continue
            for label, pattern in _PATTERNS:
                m = pattern.search(cname)
                if m:
                    out.append(Suggestion(tname, cname, label, m.group(0)))
                    break
    return out
