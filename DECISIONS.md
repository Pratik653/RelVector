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
