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

## Integrations
* Retry lock-out is keyed on `RequestContext.trace_id`. If the application does not supply a
  stable conversation id, every request is a new trace and lock-out has no effect.
* `ApprovalQueue` and audit sinks are in-process. Multi-instance deployments need a shared
  store (implement the `Approver` / `AuditSink` protocols).
* The bundled executors are minimal; production deployments should use their own pooled,
  least-privilege connections.

## Query cost
* The static score uses declared `estimated_rows`; the planner uses real statistics. They
  can disagree, and neither predicts runtime.
* Plan inspection is PostgreSQL-only.

## Benchmark
* The corpus is authored by this project. Allow labels are validated by execution on SQLite
  and PostgreSQL 16, but it is not an external standard, and the native engine was
  developed alongside it.
* Restricted-function and system-catalog categories are not yet authored.
* External tools are compared through a documented, conservative policy translation.

## CI
* The workflow and composite action have been linted and simulated locally, but have not
  run on GitHub yet.
