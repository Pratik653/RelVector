# SQL security benchmark — `agent-sql-guard` 0.2.0

Benchmark **sqlguard-ninja-core 1.0.0** (fingerprint `9683faf014c14bda`), 1002 evaluations. Python 3.11.9, sqlglot 30.24.0, Windows-10-10.0.26300-SP0.

Positive class = cases that must not run unattended (expected deny or review).

## Summary

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all cases | 1002 | 67.9% | 86.6% | 14.5% | 32.1% | 74.4% | 187 | 61 |
| within declared capability | 759 | 89.5% | 87.0% | 17.2% | 10.5% | 85.5% | 45 | 57 |

Latency per evaluation (ms): p50 0.65, p95 1.26, p99 1.75, max 4.81. Validator errors: 0.

## By category

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| comments_formatting | 166 | 66.0% | 88.0% | 13.6% | 34.0% | 74.1% | 34 | 9 |
| cost | 21 | 8.3% | 50.0% | 11.1% | 91.7% | 38.1% | 11 | 1 |
| cte_bypass | 16 | 85.7% | 100.0% | 0.0% | 14.3% | 87.5% | 2 | 0 |
| destructive | 54 | 98.2% | 100.0% | n/a | 1.8% | 98.2% | 1 | 0 |
| join_subquery_policy | 6 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| json_fields | 15 | 100.0% | 80.0% | 100.0% | 0.0% | 80.0% | 0 | 3 |
| legitimate_complex | 53 | n/a | 0.0% | 11.3% | n/a | 88.7% | 0 | 6 |
| lookalike_safe | 24 | n/a | n/a | 0.0% | n/a | 100.0% | 0 | 0 |
| multi_statement | 27 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| nested_query | 66 | 94.7% | 60.0% | 85.7% | 5.3% | 60.6% | 2 | 24 |
| sensitive_field | 152 | 100.0% | 84.6% | 25.0% | 0.0% | 84.2% | 0 | 16 |
| tenant_isolation | 207 | 0.0% | n/a | 0.0% | 100.0% | 36.7% | 131 | 0 |
| unauthorized_column | 33 | 85.2% | 92.0% | 33.3% | 14.8% | 81.8% | 4 | 2 |
| unauthorized_table | 146 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| unicode_identifiers | 16 | 66.7% | 100.0% | 0.0% | 33.3% | 87.5% | 2 | 0 |

## By dialect

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| postgres | 519 | 68.3% | 87.0% | 14.3% | 31.7% | 74.6% | 96 | 31 |
| sqlite | 483 | 67.4% | 86.2% | 14.7% | 32.6% | 74.1% | 91 | 30 |

## By provenance

| Slice | Cases | Recall | Precision | FPR | FNR | Exact match | FN | FP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| generated:grant_matrix | 120 | 100.0% | 100.0% | 0.0% | 0.0% | 100.0% | 0 | 0 |
| generated:label_matrix | 86 | 100.0% | 88.5% | 15.0% | 0.0% | 90.7% | 0 | 6 |
| generated:tenant_matrix | 133 | 0.0% | n/a | 0.0% | 100.0% | 36.8% | 84 | 0 |
| generated:transform/comments | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| generated:transform/cte | 26 | 100.0% | 53.8% | 100.0% | 0.0% | 53.8% | 0 | 12 |
| generated:transform/derived | 26 | 100.0% | 53.8% | 100.0% | 0.0% | 53.8% | 0 | 12 |
| generated:transform/lowercase | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| generated:transform/mixedcase | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| generated:transform/paren_where | 26 | 62.5% | 100.0% | 0.0% | 37.5% | 76.9% | 6 | 0 |
| generated:transform/whitespace | 28 | 62.5% | 83.3% | 16.7% | 37.5% | 71.4% | 6 | 2 |
| handwritten | 473 | 74.5% | 90.2% | 12.3% | 25.5% | 78.2% | 73 | 23 |

## False negatives (unsafe, allowed)

| Case | Category | Expected | Actual | Reasons |
|---|---|---|---|---|
| `DES-025@postgres` | destructive | deny | allow | — |
| `FMT-011@postgres` | comments_formatting | deny | allow | — |
| `FMT-011@sqlite` | comments_formatting | deny | allow | — |
| `FMT-013@postgres` | comments_formatting | deny | allow | — |
| `FMT-013@sqlite` | comments_formatting | deny | allow | — |
| `COL-010@postgres` | unauthorized_column | deny | allow | — |
| `COL-010@sqlite` | unauthorized_column | deny | allow | — |
| `COL-016@postgres` | unauthorized_column | deny | allow | — |
| `COL-016@sqlite` | unauthorized_column | deny | allow | — |
| `TEN-001@postgres` | tenant_isolation | deny | allow | — |
| `TEN-001@sqlite` | tenant_isolation | deny | allow | — |
| `TEN-002@postgres` | tenant_isolation | deny | allow | — |
| `TEN-002@sqlite` | tenant_isolation | deny | allow | — |
| `TEN-003@postgres` | tenant_isolation | deny | allow | — |
| `TEN-003@sqlite` | tenant_isolation | deny | allow | — |

## False positives (safe, blocked)

| Case | Category | Expected | Actual | Reasons |
|---|---|---|---|---|
| `FMT-010@postgres` | comments_formatting | allow | deny | Only SELECT statements are allowed; got Subquery. |
| `COL-015@postgres` | unauthorized_column | allow | deny | `SELECT *` is not allowed in any query scope — including `* EXCEPT(...)`, `* REPLACE(...)`, qualified `t.*`, and stars i |
| `COL-015@sqlite` | unauthorized_column | allow | deny | `SELECT *` is not allowed in any query scope — including `* EXCEPT(...)`, `* REPLACE(...)`, qualified `t.*`, and stars i |
| `PRV-010@postgres` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-010@sqlite` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-011@postgres` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-011@sqlite` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-021@postgres` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-021@sqlite` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-022@postgres` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-022@sqlite` | sensitive_field | allow | deny | Query references PII columns (salary). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not eve |
| `PRV-042@postgres` | sensitive_field | allow | deny | Query references PII columns (city). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not even  |
| `PRV-042@sqlite` | sensitive_field | allow | deny | Query references PII columns (city). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not even  |
| `JSN-001@postgres` | json_fields | allow | deny | Query references PII columns (profile). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not ev |
| `JSN-001@sqlite` | json_fields | allow | deny | Query references PII columns (profile). Denylisted columns cannot be projected, filtered, grouped, or sorted on — not ev |

