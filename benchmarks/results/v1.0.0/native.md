# SQL security benchmark — `native` 0.1.0

Benchmark **sqlguard-ninja-core 1.0.0** (fingerprint `9683faf014c14bda`), 1002 evaluations. Python 3.11.9, sqlglot 30.24.0, Windows-10-10.0.26300-SP0.

Positive class = cases that must not run unattended (expected deny or review).

## Summary

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all cases | 1002 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| within declared capability | 1002 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |

Latency per evaluation (ms): p50 1.30, p95 2.15, p99 2.69, max 12.99. Validator errors: 0.

## By category

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| comments_formatting | 166 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| cost | 21 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| cte_bypass | 16 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| destructive | 54 | 100.0% | 100.0% | n/a | 0.0% | 100.0% | 0 | 0 |
| join_subquery_policy | 6 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| json_fields | 15 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| legitimate_complex | 53 | n/a | n/a | 0.0% | n/a | 100.0% | 0 | 0 |
| lookalike_safe | 24 | n/a | n/a | 0.0% | n/a | 100.0% | 0 | 0 |
| multi_statement | 27 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| nested_query | 66 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| sensitive_field | 152 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| tenant_isolation | 207 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| unauthorized_column | 33 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| unauthorized_table | 146 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| unicode_identifiers | 16 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |

## By dialect

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | 519 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| sqlite | 483 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |

## By provenance

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| generated:grant_matrix | 120 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:label_matrix | 86 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:tenant_matrix | 133 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/comments | 28 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/cte | 26 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/derived | 26 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/lowercase | 28 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/mixedcase | 28 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/paren_where | 26 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/whitespace | 28 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| handwritten | 473 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |

## False negatives (unsafe, allowed)

None.

## False positives (safe, blocked)

None.

