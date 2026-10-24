# SQL security benchmark — `sql-guardrail` 0.5.2

Benchmark **sqlguard-ninja-core 1.0.0** (fingerprint `9683faf014c14bda`), 1002 evaluations. Python 3.11.9, sqlglot 30.24.0, Windows-10-10.0.26300-SP0.

Positive class = cases that must not run unattended (expected deny or review).

## Summary

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all cases | 1002 | 98.6% | 86.6% | 21.2% | 1.4% | 89.2% | 8 | 89 |
| within declared capability | 835 | 98.3% | 87.5% | 19.3% | 1.7% | 90.5% | 8 | 68 |

Latency per evaluation (ms): p50 0.90, p95 1.72, p99 2.12, max 7.60. Validator errors: 0.

## By category

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| comments_formatting | 166 | 100.0% | 92.6% | 12.1% | 0.0% | 95.2% | 0 | 8 |
| cost | 21 | 75.0% | 64.3% | 55.6% | 25.0% | 57.1% | 3 | 5 |
| cte_bypass | 16 | 100.0% | 100.0% | 0.0% | 0.0% | 87.5% | 0 | 0 |
| destructive | 54 | 100.0% | 100.0% | n/a | 0.0% | 100.0% | 0 | 0 |
| join_subquery_policy | 6 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| json_fields | 15 | 100.0% | 80.0% | 100.0% | 0.0% | 80.0% | 0 | 3 |
| legitimate_complex | 53 | n/a | 0.0% | 18.9% | n/a | 81.1% | 0 | 10 |
| lookalike_safe | 24 | n/a | 0.0% | 8.3% | n/a | 91.7% | 0 | 2 |
| multi_statement | 27 | 100.0% | 94.7% | 11.1% | 0.0% | 96.3% | 0 | 1 |
| nested_query | 66 | 100.0% | 61.3% | 85.7% | 0.0% | 63.6% | 0 | 24 |
| sensitive_field | 152 | 100.0% | 83.0% | 28.1% | 0.0% | 82.9% | 0 | 18 |
| tenant_isolation | 207 | 98.5% | 90.2% | 18.4% | 1.5% | 92.3% | 2 | 14 |
| unauthorized_column | 33 | 92.6% | 92.6% | 33.3% | 7.4% | 87.9% | 2 | 2 |
| unauthorized_table | 146 | 98.7% | 100.0% | 0.0% | 1.3% | 99.3% | 1 | 0 |
| unicode_identifiers | 16 | 100.0% | 75.0% | 20.0% | 0.0% | 87.5% | 0 | 2 |

## By dialect

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | 519 | 98.4% | 86.1% | 22.2% | 1.7% | 88.6% | 5 | 48 |
| sqlite | 483 | 98.9% | 87.1% | 20.1% | 1.1% | 89.9% | 3 | 41 |

## By provenance

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| generated:grant_matrix | 120 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:label_matrix | 86 | 100.0% | 88.5% | 15.0% | 0.0% | 90.7% | 0 | 6 |
| generated:tenant_matrix | 133 | 100.0% | 92.3% | 14.3% | 0.0% | 94.7% | 0 | 7 |
| generated:transform/comments | 28 | 100.0% | 88.9% | 16.7% | 0.0% | 92.9% | 0 | 2 |
| generated:transform/cte | 26 | 100.0% | 53.8% | 100.0% | 0.0% | 53.8% | 0 | 12 |
| generated:transform/derived | 26 | 100.0% | 53.8% | 100.0% | 0.0% | 53.8% | 0 | 12 |
| generated:transform/lowercase | 28 | 100.0% | 88.9% | 16.7% | 0.0% | 92.9% | 0 | 2 |
| generated:transform/mixedcase | 28 | 100.0% | 88.9% | 16.7% | 0.0% | 92.9% | 0 | 2 |
| generated:transform/paren_where | 26 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:transform/whitespace | 28 | 100.0% | 88.9% | 16.7% | 0.0% | 92.9% | 0 | 2 |
| handwritten | 473 | 97.2% | 86.3% | 23.5% | 2.8% | 87.1% | 8 | 44 |

## False negatives (unsafe, allowed)

| Case | Category | Expected | Actual | Reasons |
|---|---|---|---|---|
| `TAB-007@postgres` | unauthorized_table | deny | allow | — |
| `COL-016@postgres` | unauthorized_column | deny | allow | — |
| `COL-016@sqlite` | unauthorized_column | deny | allow | — |
| `TEN-037@postgres` | tenant_isolation | deny | allow | — |
| `TEN-037@sqlite` | tenant_isolation | deny | allow | — |
| `CST-011@postgres` | cost | review | allow | — |
| `CST-012@postgres` | cost | review | allow | — |
| `CST-012@sqlite` | cost | review | allow | — |

## False positives (safe, blocked)

| Case | Category | Expected | Actual | Reasons |
|---|---|---|---|---|
| `MUL-105@postgres` | multi_statement | allow | deny | PARSE_ERROR |
| `COL-015@postgres` | unauthorized_column | allow | deny | SELECT_STAR |
| `COL-015@sqlite` | unauthorized_column | allow | deny | SELECT_STAR |
| `PRV-001@postgres` | sensitive_field | allow | deny | MISSING_REQUIRED_PREDICATE |
| `PRV-001@sqlite` | sensitive_field | allow | deny | MISSING_REQUIRED_PREDICATE |
| `PRV-010@postgres` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-010@sqlite` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-011@postgres` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-011@sqlite` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-021@postgres` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-021@sqlite` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-022@postgres` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-022@sqlite` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-042@postgres` | sensitive_field | allow | deny | COLUMN_DENIED |
| `PRV-042@sqlite` | sensitive_field | allow | deny | COLUMN_DENIED |

