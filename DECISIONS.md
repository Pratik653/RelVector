# Decisions log

Architecture decisions are recorded in [docs/architecture/ARCHITECTURE_DECISIONS.md](docs/architecture/ARCHITECTURE_DECISIONS.md).
This file logs smaller implementation decisions.

| Date | Decision | Why |
|---|---|---|
| 2026-10-24 | Use sqlglot `qualify` + `traverse_scope` for attribution | Mature, MIT, handles CTE/derived-table scoping |
| 2026-10-24 | Unknown and ungranted tables return the same agent-facing message | Avoids schema enumeration through the guard |
| 2026-10-24 | Lone-surrogate / NUL input denied before parsing | Never-raise contract; drivers reject it anyway |
| 2026-10-24 | pytest `--basetemp=.pytest_tmp` | The default Windows temp dir is not writable in this environment |
| 2026-10-24 | Benchmark labels may be corrected only with evidence from a real engine | e.g. FMT-010 rejected by SQLite |
| 2026-10-24 | External validators run as JSON Lines workers in their own venvs | Import-name collision and incompatible sqlglot pins (ADR-004) |
| 2026-10-24 | agent-sql-guard evaluated via `evaluate(sql, bytes_processed=0)` | Its static pass returns CONFIRM pending cost; zero-byte dry run isolates static rules |
| 2026-10-24 | LangGraph context read from run config, execute node re-validates | Nodes can write state but not config; forged state flags gain nothing |
| 2026-10-24 | Compare fails on changed expected labels | Relabelling is the easiest way to hide a regression |
| 2026-10-24 | Baseline for PRs read from the base branch in the action | A PR cannot approve its own regression |
| 2026-10-24 | Cast of the tenant column is not a pin | Casts can be lossy (text '01' vs '1') |
| 2026-10-24 | Redaction marker is a neutral `?` | Dialect placeholders (`%s`) are confusing in audit logs |
| 2026-10-24 | Rewrote local history to the GitHub noreply address before first push | Maintainer's email privacy requirement; history never published |
