# Changelog

All notable changes are documented here. The project follows
[Semantic Versioning](https://semver.org/); before 1.0, minor versions may change the API.

## [0.1.0] — unreleased

First release.

### Added
* Policy schema v1: catalog, classification labels, roles, tenant settings, function policy,
  limits, cost thresholds, disclosure mode. Policies are validated on load.
* Guard and rules on sqlglot 30: read-only statements, system catalogs, functions,
  table/column grants, privacy labels (deny / aggregate-only / review, JSON paths, small
  cohort, minimisation), tenant isolation, structure limits, static cost score.
* `SQLCheckpoint` with block / review / audit modes, approvals bound to the SQL hash
  (single use, expiry, no self-approval), retry lock-out, redacted audit events.
* LangChain tool, LangGraph nodes and router, FastAPI router, read-only executors.
* PostgreSQL `EXPLAIN (FORMAT JSON)` inspector with guard gating and a read-only,
  time-limited, rolled-back transaction.
* Benchmark corpus v1.0.0 (530 cases, 1,002 evaluations), seeded generator, metrics,
  adapters (native, callable, isolated external workers for three existing tools), JSON
  and Markdown reports, baseline comparison with a label-change gate.
* `sqlninja` CLI and a composite GitHub Action.

### Fixed during development (each with a regression test)
* Unknown select-list columns were allowed when qualification aliased them to themselves.
* `Guard.validate` raised on lone UTF-16 surrogates.
* Quoted mixed-case identifiers were re-lowercased, so PostgreSQL `"Orders"` matched `orders`.
* A cast of the tenant column was accepted as a tenant pin.
* LangGraph nodes did not receive the run config (it needs a `RunnableConfig` annotation).
* The shared SQLite connection could not be used from FastAPI worker threads.
* CLI output crashed on cp1252 consoles.
