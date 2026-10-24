# Known limitations

Static SQL inspection is one layer. It does not replace database permissions, row-level
security, statement timeouts, resource limits or authentication.

## Scope
* Read-only workloads only (v0.1). All writes are denied.
* Dialects: PostgreSQL and SQLite are tested. Other sqlglot dialects parse but are
  **experimental** and not covered by the benchmark.
* Policy identifiers are matched in lower case. Quoted mixed-case table names
  (`"Orders"` in PostgreSQL) are treated as unknown tables and denied.

## Analysis
* Tenant isolation is checked per scope: a tenant filter in an outer query does not satisfy
  a CTE/derived table that reads the table unfiltered. That is safe but gives false positives.
  Predicates under `OR`/`NOT` are ignored, which can also give false positives.
* `aggregate_only` columns are checked where they are referenced. Aggregating a CTE output
  that projects the raw column is denied (false positive).
* Small-cohort protection is heuristic: it flags filters/grouping on columns marked
  `identifying`. k-anonymity / minimum group size is not enforced.
* JSON paths are recognised for `->`, `->>`, `#>>` and `json_extract` with literal paths.
  Dynamic keys are treated as reading the whole document.
* User-defined functions are unknown to the parser. By default they only produce a warning;
  use `functions.mode: allowlist` in production.
* Static cost scores are heuristics based on catalog row estimates, not runtime predictions.

## Benchmark
* The corpus is authored by this project and validated against SQLite. It is not an external
  standard. Restricted-function and system-catalog categories are not yet authored.
