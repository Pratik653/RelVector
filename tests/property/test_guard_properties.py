"""Property-based invariants of the guard."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sqlguard_ninja import Decision, Guard, Policy
from tests.conftest import POLICY_PATH

GUARD = Guard(Policy.from_file(POLICY_PATH))
CTX = {"tenant_id": 1}
SAFE = "SELECT o.id, o.status FROM orders o WHERE o.tenant_id = 1"
settings.register_profile("ci", max_examples=150, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("ci")


@given(st.text(max_size=300))
def test_never_raises_on_arbitrary_text(text):
    r = GUARD.validate(text, role="support_analyst", context=CTX)
    assert r.decision in set(Decision)


# Valid Unicode text only: lone surrogates are rejected up front (see test_rules regression).
@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="*/\x00"),
        max_size=40,
    )
)
def test_block_comment_never_changes_safe_decision(comment):
    sql = SAFE.replace(" FROM ", f" /*{comment}*/ FROM ")
    assert GUARD.validate(sql, role="support_analyst", context=CTX).decision is Decision.ALLOW


@given(
    st.sampled_from(["select", "SELECT", "Select", "sElEcT"]),
    st.sampled_from([" ", "\n", "\t", "  \n\t "]),
)
def test_case_and_whitespace_invariance(kw, ws):
    sql = f"{kw}{ws}o.id{ws}FROM{ws}orders o{ws}WHERE{ws}o.tenant_id = 1"
    assert GUARD.validate(sql, role="support_analyst", context=CTX).allowed


@given(st.integers(min_value=2, max_value=10**9))
def test_any_other_tenant_is_denied(tenant):
    sql = f"SELECT o.id FROM orders o WHERE o.tenant_id = {tenant}"
    assert GUARD.validate(sql, role="support_analyst", context=CTX).denied


@given(st.sampled_from(["OR 1=1", "OR TRUE", "OR o.id > 0", "OR o.tenant_id = 2"]))
def test_disjunction_never_satisfies_tenant(suffix):
    sql = f"SELECT o.id FROM orders o WHERE o.tenant_id = 1 {suffix}"
    assert GUARD.validate(sql, role="support_analyst", context=CTX).denied


@given(st.text(max_size=60))
def test_deterministic(text):
    a = GUARD.validate(text, role="support_analyst", context=CTX)
    b = GUARD.validate(text, role="support_analyst", context=CTX)
    assert (a.decision, [f.rule_id for f in a.findings]) == (
        b.decision,
        [f.rule_id for f in b.findings],
    )
