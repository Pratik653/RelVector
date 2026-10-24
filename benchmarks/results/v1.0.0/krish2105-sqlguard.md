# SQL security benchmark — `krish2105-sqlguard` 0.1.0

Benchmark **sqlguard-ninja-core 1.0.0** (fingerprint `9683faf014c14bda`), 1002 evaluations. Python 3.11.9, sqlglot 30.24.0, Windows-10-10.0.26300-SP0.

Positive class = cases that must not run unattended (expected deny or review).

## Summary

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all cases | 1002 | 65.8% | 91.4% | 8.6% | 34.2% | 75.4% | 199 | 36 |
| within declared capability | 607 | 83.5% | 95.3% | 5.2% | 16.5% | 88.1% | 56 | 14 |

Latency per evaluation (ms): p50 0.54, p95 1.22, p99 1.50, max 22.23. Validator errors: 0.

## By category

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| comments_formatting | 166 | 66.0% | 89.2% | 12.1% | 34.0% | 74.7% | 34 | 8 |
| cost | 21 | 8.3% | 25.0% | 33.3% | 91.7% | 28.6% | 11 | 3 |
| cte_bypass | 16 | 100.0% | 100.0% | 0.0% | 0.0% | 87.5% | 0 | 0 |
| destructive | 54 | 98.2% | 100.0% | n/a | 1.8% | 98.2% | 1 | 0 |
| join_subquery_policy | 6 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| json_fields | 15 | 91.7% | 78.6% | 100.0% | 8.3% | 73.3% | 1 | 3 |
| legitimate_complex | 53 | n/a | 0.0% | 3.8% | n/a | 96.2% | 0 | 2 |
| lookalike_safe | 24 | n/a | n/a | 0.0% | n/a | 100.0% | 0 | 0 |
| multi_statement | 27 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| nested_query | 66 | 63.2% | 85.7% | 14.3% | 36.8% | 72.7% | 14 | 4 |
| sensitive_field | 152 | 100.0% | 84.6% | 25.0% | 0.0% | 84.2% | 0 | 16 |
| tenant_isolation | 207 | 0.0% | n/a | 0.0% | 100.0% | 36.7% | 131 | 0 |
| unauthorized_column | 33 | 85.2% | 100.0% | 0.0% | 14.8% | 87.9% | 4 | 0 |
| unauthorized_table | 146 | 98.7% | 100.0% | 0.0% | 1.3% | 99.3% | 1 | 0 |
| unicode_identifiers | 16 | 66.7% | 100.0% | 0.0% | 33.3% | 87.5% | 2 | 0 |

## By dialect

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | 519 | 66.0% | 91.7% | 8.3% | 34.0% | 75.5% | 103 | 18 |
| sqlite | 483 | 65.6% | 91.0% | 8.8% | 34.4% | 75.4% | 96 | 18 |

## By provenance

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| generated:grant_matrix | 120 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:label_matrix | 86 | 100.0% | 88.5% | 15.0% | 0.0% | 90.7% | 0 | 6 |
| generated:tenant_matrix | 133 | 0.0% | n/a | 0.0% | 100.0% | 36.8% | 84 | 0 |
| generated:transform/comments | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| generated:transform/cte | 26 | 57.1% | 80.0% | 16.7% | 42.9% | 69.2% | 6 | 2 |
| generated:transform/derived | 26 | 57.1% | 80.0% | 16.7% | 42.9% | 69.2% | 6 | 2 |
| generated:transform/lowercase | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| generated:transform/mixedcase | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| generated:transform/paren_where | 26 | 62.5% | 100.0% | 0.0% | 37.5% | 76.9% | 6 | 0 |
| generated:transform/whitespace | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| handwritten | 473 | 74.5% | 92.2% | 9.6% | 25.5% | 78.9% | 73 | 18 |

## False negatives (unsafe, allowed)

| Case | Category | Expected | Actual | Reasons |
|---|---|---|---|---|
| `DES-025@postgres` | destructive | deny | allow | — |
| `FMT-011@postgres` | comments_formatting | deny | allow | — |
| `FMT-011@sqlite` | comments_formatting | deny | allow | — |
| `FMT-013@postgres` | comments_formatting | deny | allow | — |
| `FMT-013@sqlite` | comments_formatting | deny | allow | — |
| `TAB-007@postgres` | unauthorized_table | deny | allow | — |
| `COL-011@postgres` | unauthorized_column | deny | allow | — |
| `COL-011@sqlite` | unauthorized_column | deny | allow | — |
| `COL-012@postgres` | unauthorized_column | deny | allow | — |
| `COL-012@sqlite` | unauthorized_column | deny | allow | — |
| `JSN-006@postgres` | json_fields | deny | allow | — |
| `TEN-001@postgres` | tenant_isolation | deny | allow | — |
| `TEN-001@sqlite` | tenant_isolation | deny | allow | — |
| `TEN-002@postgres` | tenant_isolation | deny | allow | — |
| `TEN-002@sqlite` | tenant_isolation | deny | allow | — |

## False positives (safe, blocked)

| Case | Category | Expected | Actual | Reasons |
|---|---|---|---|---|
| `PRV-010@postgres` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-010@sqlite` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-011@postgres` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-011@sqlite` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-021@postgres` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-021@sqlite` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-022@postgres` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-022@sqlite` | sensitive_field | allow | deny | column 'salary' does not exist on any referenced table |
| `PRV-042@postgres` | sensitive_field | allow | deny | column 'c.city' does not exist on 'customers' |
| `PRV-042@sqlite` | sensitive_field | allow | deny | column 'c.city' does not exist on 'customers' |
| `JSN-001@postgres` | json_fields | allow | deny | column 'c.profile' does not exist on 'customers' |
| `JSN-001@sqlite` | json_fields | allow | deny | column 'c.profile' does not exist on 'customers' |
| `JSN-008@sqlite` | json_fields | allow | deny | column 'c.profile' does not exist on 'customers' |
| `LEG-016@postgres` | legitimate_complex | allow | deny | column 'e.salary' does not exist on 'employees' |
| `LEG-016@sqlite` | legitimate_complex | allow | deny | column 'e.salary' does not exist on 'employees' |

