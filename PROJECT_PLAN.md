# Project plan

| Milestone | Contents | Acceptance criteria |
|---|---|---|
| M1 Foundation | policy schema, analyser, rules, guard, tests | lint/type clean; ≥85% coverage; corpus tests pass |
| M2 Benchmark | corpus ≥500 cases, runner, metrics, adapters, compare, CLI | reproducible JSON + Markdown reports; external adapters run in isolated venvs |
| M3 Agents | checkpoint modes, approvals, audit, LangChain, LangGraph, FastAPI, examples | retry/rephrase/approval-claim bypass tests pass |
| M4 Cost | static score, PostgreSQL EXPLAIN inspector, Docker Compose | inspector tests pass against real PostgreSQL |
| M5 CI | workflow, composite action, baseline gate | gate fails on a seeded regression; SHA-pinned actions |
| M6 Release | docs, threat model, release checks | all checks pass; maintainer approval before publication |

Dependencies: M2 needs M1. M3, M4, M5 need M1, and M5 needs M2's compare logic.
