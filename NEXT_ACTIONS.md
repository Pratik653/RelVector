# Next actions

_Updated 2026-10-24. On resume: read IMPLEMENTATION_STATUS.md, run
`.venv/Scripts/python -m pytest -q` and `git log --oneline`, then continue from the top._

1. **Corpus** — add the remaining categories as case files under
   `benchmarks/datasets/v1/cases/`: unauthorized tables/columns, privacy & aggregates, tenant
   isolation, CTE/nested bypasses, unicode identifiers, legitimate complex, look-alike safe,
   cost, dialect-specific, JSON fields. Add `scripts/generate_corpus.py` for role×table grant
   and tenant-pattern matrices.
   - Restricted-function / system-catalog cases: not authored (see status file). Needs a
     maintainer contribution.
2. **Benchmark engine** — runner, adapters (native / callable / subprocess workers for
   sql-guardrail, agent-sql-guard, krish2105/sqlguard), metrics (precision, recall, FPR, FNR,
   per-category, per-dialect, latency percentiles), JSON + Markdown reports, compare.
3. **CLI** — `sqlninja validate | policy check | benchmark run | benchmark compare | report`.
4. **Agent integrations** — `SQLCheckpoint` (block/audit/review, hash-bound approvals, retry
   lockout, audit sink with redaction), LangChain tool, LangGraph node, FastAPI router, examples.
5. **PostgreSQL** — `EXPLAIN (FORMAT JSON)` inspector with read-only txn + timeout; tests via
   `pgserver` locally and a service container in CI; Docker Compose file.
6. **CI** — workflow with SHA-pinned actions, composite action, baseline regression gate.
7. **Docs** — README, threat model, methodology, guides, SECURITY/CONTRIBUTING/etc.
8. Release checks, then ask the maintainer for publication approval. Do not publish before.
