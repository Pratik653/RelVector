# Competitive analysis

_Research date: 2026-10-24. Every statement about another project was checked against its
source code at the commit listed below, not only its README. Re-verify before relying on it:
these projects move quickly._

## 1. Method

1. Shallow-cloned each candidate repository into a scratch area **outside** this repository.
2. Read README, docs, `pyproject.toml`, source modules and tests.
3. Created one isolated virtual environment per project (Python 3.13, Windows 11) and ran its
   own test suite unmodified.
4. Queried the public GitHub API for stars, open issues, PRs and last push.
5. Queried PyPI (`pip index versions`) for the published package names.

| Project | Commit inspected | Licence (verified) | PyPI | Own tests (local run) |
|---|---|---|---|---|
| [nickusevich/sql-guardrail](https://github.com/nickusevich/sql-guardrail) | [`eadfb9d`](https://github.com/nickusevich/sql-guardrail/commit/eadfb9d0c725f4960621a7c67c23219103710c5b) (2026-06-09, v0.5.2) | MIT (`LICENSE` file) | `sql-guardrail` 0.5.2 | 516 passed, 26 errors (all `PermissionError` creating temp dirs in `tests/unit/test_cli.py` on Windows; environmental, not a logic failure) |
| [sakura-sky/sql-guard](https://github.com/sakura-sky/sql-guard) | [`5c0e5f8`](https://github.com/sakura-sky/sql-guard/commit/5c0e5f8eef011cc48c4b4b8929d269a19125bd39) (2026-08-17, v0.2.0) | Apache-2.0 **declared in `pyproject.toml` only — no `LICENSE` file in the repository**; GitHub API reports no licence | `agent-sql-guard` 0.2.0 | 204 passed |
| [krish2105/sqlguard](https://github.com/krish2105/sqlguard) | [`62327f2`](https://github.com/krish2105/sqlguard/commit/62327f214ed8c9ea82ecf820bf04c4b55a6161a2) (2026-07-18, v0.1.0, 2 commits) | MIT | **Not published** (`pip install sqlguard` in its README does not resolve) | 35 passed |
| [zeredbaron/proxql](https://github.com/zeredbaron/proxql) (found during research) | [`a909ce0`](https://github.com/zeredbaron/proxql/commit/a909ce0adc0f9c05dd968d0bfc583b7db30a1099) (2026-03-22) | Apache-2.0 | `proxql` 0.1.0 (alpha) | not run (Python + TypeScript monorepo; read only) |
| [tobymao/sqlglot](https://github.com/tobymao/sqlglot) | latest release 30.24.0 | MIT | `sqlglot` 30.24.0 | not run (mature upstream; ~9.7k stars, pushed 2026-10-23) |

Popularity at time of research (GitHub API): sql-guardrail 5 stars, sql-guard 0, krish2105/sqlguard 0,
proxql 5, sqlglot ≈9.7k. None of the three named guards had open issues; sql-guard had one merged PR
(an eight-bypass security fix, [#1](https://github.com/sakura-sky/sql-guard/pull/1)).

Adjacent tools reviewed for scope (not validators of security policy):

* **LangChain `SQLDatabaseToolkit` / `QuerySQLCheckerTool`** — the checker asks an LLM to review
  the query; it is a correctness aid, not an enforcement boundary. The toolkit's own guidance tells
  the *agent* to call the checker, which is not enforced in code.
* **Guardrails AI `valid_sql`** — checks syntax (via `sqlvalidator` or by running the statement
  against a database). No table/column/tenant policy. Repository archived; moved to the hub monorepo.
* **SQLFluff** — SQL linter/formatter. Excellent for style; not a security control.
* **Academic benchmarks** — SecureSQL (932 privacy-risk NL samples built on Spider/BIRD) and
  ShieldSQL (540 multi-turn samples) evaluate *LLM behaviour* on natural-language prompts. They do
  not evaluate a SQL policy engine on concrete SQL with a declared schema, role and expected
  decision. Their licences were not verified, so **no data from them is used here.**

## 2. Important findings from source inspection

1. **Import-name collision.** `sql-guardrail` and krish2105's project both install a top-level
   module called `sqlguard`. They cannot coexist in one environment.
2. **Incompatible sqlglot pins.** `agent-sql-guard` requires `sqlglot>=25,<27`; `sql-guardrail`
   requires `sqlglot>=30,<31`. They cannot coexist either.
   → Findings 1 and 2 make in-process, side-by-side comparison impossible. This drove the
   decision to run external validators in **isolated subprocess workers** (see ADR-004).
3. **sql-guardrail is the most thorough read-only validator** of the group: a statement-kind
   allowlist with `exp.Command` default-deny, a tautology catch-all, a denied-identifier catch-all,
   an opt-in function allowlist, AST-size caps, `require_predicate` for tenant filters, and a
   47-file malicious corpus. It deliberately uses sqlglot's dialect-neutral parser
   ([docs/ARCHITECTURE.md](https://github.com/nickusevich/sql-guardrail/blob/eadfb9d0c725f4960621a7c67c23219103710c5b/docs/ARCHITECTURE.md)).
   It has no notion of roles, data classification labels, aggregate-only access, review/approval,
   audit events, agent framework integration, or cost/plan inspection.
4. **agent-sql-guard** has the best PII design of the group: a `reference` vs `project` mode,
   per-scope column checks, and explicit refusal of `SELECT *` and whole-row references because it
   has **no schema**. Its cost cap consumes a bytes-processed number supplied by the caller
   (BigQuery dry-run). It returns `allow/confirm/deny`, but `confirm` is only used for cost.
   It has no roles, tenant predicates or agent integrations (an optional Google ADK extra exists).
5. **krish2105/sqlguard** is small (~950 lines incl. tests): read-only AST check, function and
   catalog deny-lists, a schema allow-list, LIMIT injection/clamping, transpilation, and a
   regex-based natural-language "question screen". Its README advertises a PyPI install that does
   not exist, and a "100% blocked" badge that refers to a 29-case set in another project.
6. **proxql** offers statement-mode presets and a table allowlist with LangChain/FastAPI
   *examples*. No column, tenant or PII rules are documented.
7. **No project pins GitHub Actions to commit SHAs.** All use tags such as `actions/checkout@v4`.

## 3. Feature matrix

Legend: ✅ supported and verified in source/tests · 🟡 partial · 🧪 experimental · ❌ missing ·
❔ could not verify. "SQLGuard Ninja" reflects the state of **this** repository at v0.1.0; see
[`IMPLEMENTATION_STATUS.md`](../../IMPLEMENTATION_STATUS.md) for evidence.

| # | Capability | sql-guardrail 0.5.2 | agent-sql-guard 0.2.0 | krish2105/sqlguard 0.1.0 | proxql 0.1.0 | SQLGuard Ninja 0.1.0 |
|---|---|---|---|---|---|---|
| 1 | SQL validation (read-only, multi-stmt, DDL) | ✅ statement allowlist + `Command` default-deny | ✅ | ✅ | ✅ (docs) | ✅ (built on sqlglot, same default-deny approach) |
| 2 | LangGraph integration | ❌ | ❌ | ❌ | ❌ | ✅ guard node + router + runnable demo |
| 3 | LangChain integration | ❌ | ❌ | ❌ | 🟡 example only | ✅ `BaseTool` whose args schema cannot carry role/tenant |
| 4 | Multi-agent / approval workflows | ❌ | 🟡 `confirm` outcome for cost only | ❌ | ❌ | ✅ block / audit / review modes, hash-bound approvals, retry lockout |
| 5 | SQL security benchmark | 🟡 47 malicious + 10 benign files, pass/fail only | ❌ | 🟡 29-row CSV of NL questions | ❌ | ✅ versioned corpus, metrics, adapters, comparison |
| 6 | Privacy / sensitive-data policy | 🟡 column allow/deny lists | ✅ PII denylist, reference/project modes | 🟡 schema allow-list | ❌ | ✅ labels, roles, aggregate-only, JSON paths, alternatives |
| 7 | Query-cost analysis | 🟡 static caps (joins, depth, LIMIT, AST size) | 🟡 caller-supplied dry-run bytes | 🟡 LIMIT clamp | ❌ | ✅ static risk score + PostgreSQL `EXPLAIN (FORMAT JSON)` |
| 8 | GitHub Actions integration | ❌ (own CI only) | ❌ | ❌ | ❌ | ✅ composite action + baseline regression gate |
| 9 | Multi-dialect | 🟡 neutral parser only, by design | ✅ dialect parameter, 7 dialects tested | ✅ source/target dialect | ✅ (docs claim 20+) | 🟡 PostgreSQL + SQLite tested; others parse but are not tested |
| 10 | Extensibility | ✅ rule functions | ✅ `Rule` protocol | 🟡 | ❔ | ✅ `Rule` protocol, benchmark adapters, custom validators |
| 11 | Developer experience | ✅ CLI, HTTP sidecar, Docker image | ✅ library | ✅ CLI | ✅ | ✅ CLI, SDK, FastAPI router, examples |
| 12 | Test coverage | ✅ 500+ tests, coverage in CI | ✅ 204 tests | 🟡 35 tests | ❔ | see status file (measured, not estimated) |
| 13 | Performance data | ❔ none published | ❔ none published | ❔ none published | ❔ | ✅ p50/p95/p99 reported by every benchmark run |
| 14 | Licensing | ✅ MIT | 🟡 Apache-2.0 declared, no LICENSE file | ✅ MIT | ✅ Apache-2.0 | ✅ Apache-2.0 |
| 15 | Maintenance activity | 🟡 6 commits, last 2026-06-09 | 🟡 9 commits, last 2026-08-17 | 🟡 2 commits, 2026-07-18 | 🟡 last 2026-03-22 | new |

## 4. Gaps worth filling (and things deliberately not duplicated)

**Real gaps:**

1. **No shared, labelled benchmark for SQL policy engines.** The existing corpora are pass/fail
   fixtures owned by one tool. None reports precision, false-positive rate or latency, or keeps
   expected decisions independent of the tool under test.
2. **No role- and classification-aware policy.** Real deployments say "support may see order status but
   not card numbers; HR may see salary only in aggregate". Allow/deny lists do not capture that.
3. **No agent-side enforcement contract.** None of the tools separates *policy evaluation* from
   *execution authorization*, binds approvals to the exact SQL, or stops retry loops.
4. **No pre-execution plan inspection with safety gates.** Cost checks are either static caps or
   depend on caller-supplied numbers.
5. **No CI regression gate** that fails a PR when a previously blocked unsafe query becomes allowed.

**Not duplicated:**

* SQL parsing, dialect handling, scope analysis and column qualification come from **sqlglot**
  (MIT, a dependency, no code copied).
* Linting/formatting is left to SQLFluff.
* sql-guardrail's catch-all tautology checker is **not** re-implemented. Instead, its *adapter*
  lets users benchmark it against the same corpus and run both if they want. Our tenant rule takes
  a different approach: only top-level conjuncts that compare the tenant column to the trusted
  context value count. `OR 1=1` cannot satisfy it, so a tautology catch-all is not needed for
  that guarantee.

## 5. Licence review summary

* No third-party source code is copied into this repository.
* External validators are installed **as dependencies** in isolated adapter environments created
  by `scripts/setup_external_adapters.py`. They are not vendored or redistributed.
* agent-sql-guard's missing `LICENSE` file is noted. We only *install* it from PyPI for optional
  benchmarking and never redistribute it, so its licence text is not required here. Users should
  check the licence themselves before redistributing it.
* Full dependency attribution: [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).
