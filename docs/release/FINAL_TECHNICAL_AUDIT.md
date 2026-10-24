# Final technical audit — v0.1.0

_Performed 2026-10-24. The previous session's claims were re-checked directly; nothing below
is copied from earlier status reports without being re-run._

Legend: **Verified** = re-executed in this audit, with output inspected. **Implemented,
unverified** = the code exists but this environment could not exercise it.

## 1. Repository state

| Item | Finding | Status |
|---|---|---|
| Working tree | clean before the audit | Verified |
| Branches / remotes / tags | `main` only; no remote; no tags; local `backup/pre-email-rewrite` (never pushed) | Verified |
| History | 6 commits; author and committer rewritten from a private address to the GitHub-verified noreply address (obtained via `gh api user/emails`); file tree byte-identical to the backup | Verified |
| Personal email | 0 hits in commit metadata, 0 in the contents of any commit, 0 in the working tree | Verified |
| Repo-local git identity | `user.name=Pratik653`, `user.email=<id>+Pratik653@users.noreply.github.com` | Verified |
| Target repository | `Pratik653/SQLGuard_Ninjapy` does not exist yet (HTTP 404) | Verified |

## 2. Workstreams

| Workstream | What exists | Verified working | Incomplete / caveats |
|---|---|---|---|
| A. Benchmarking | Corpus v1.0.0: 530 cases / 1,002 evaluations; generator with `--check`; runner, metrics, adapters (native, callable, three isolated external tools), JSON + Markdown reports, baseline compare with security/usability/label-change/error classes | All cases evaluated by the per-case test suite. Allow-labels executed on SQLite and PostgreSQL 16. External adapters run. | **Restricted-function and system-catalog cases are absent** (see §6). The native score reflects a co-developed corpus. |
| B. LangGraph / LangChain | `SQLCheckpoint` (block/review/audit), hash-bound approvals, retry lock-out, trace ids, redacted audit; LangChain tool; LangGraph guard/execute nodes and router; FastAPI router; deterministic examples | Tests cover tampered graph state, extra tool args, retry lock-out, approvals, audit mode, and DB-level write refusal. All examples run in tests. | Real-LLM example is optional and was not executed (needs an API key). |
| C. Privacy | Explicit labels, role access (deny / aggregate_only / review), column overrides, JSON-path labels, small-cohort review, minimisation hints, generic disclosure | Unit, corpus and property tests. Decisions use sqlglot scope attribution, not string matching (e.g. aliases, CTEs, `*` expansion, whole-row references). | Reference-based semantics give documented false positives for CTE lineage. Not a GDPR certification. |
| D. Query cost | Static score with documented weights; PostgreSQL EXPLAIN inspector; Docker Compose file; synthetic data | Inspector tested on embedded PostgreSQL 16.2, including a non-execution proof (division by zero plans fine) and refusal of non-allowed SQL | **Docker Compose is not verified locally** (no Docker); it runs in a CI job. |
| E. CI | `ci.yml` (lint, types, tests 3.11–3.13 on Linux and Windows, PostgreSQL service, Compose, gate, external tools, package build); composite `action.yml`; consumer example | actionlint clean; action shell steps simulated locally for pass and fail paths | **Not yet run on GitHub**; status recorded after publication. |

## 3. Quality gates (re-run in this audit)

| Check | Result |
|---|---|
| Tests, Python 3.11.9 (Windows), incl. 225 on PostgreSQL 16.2 | 1,646 passed, 0 failed (before the README additions; the final count is in RELEASE_CHECKLIST.md) |
| Coverage (branch, `sqlguard_ninja`, no exclusions beyond `TYPE_CHECKING`/protocol stubs) | 95% |
| ruff check / ruff format --check | pass |
| mypy --strict | pass |
| Corpus generator `--check` | pass |
| `python -m build` + `twine check` | pass (wheel and sdist) |
| Clean wheel install on Python 3.13 | pass |
| pip-audit (installed dependency set) | no known vulnerabilities |
| gitleaks 8.30.1 on publishable history (6 commits) | no leaks |
| gitleaks on the directory | 4 findings, all false positives in git-ignored third-party `setuptools` inside local venvs; none in the 131 tracked files |
| Documentation | README CLI/SDK/privacy/cost outputs, policy-reference sample and custom-rule snippet are executed by tests; all relative Markdown links resolve |

## 4. Security review

* No secrets, tokens, private keys or real personal data in tracked files or history.
  Fixture data is synthetic: the test PAN 4111…, `example.com` domains.
* Two throwaway database passwords appear deliberately in `docker/docker-compose.yml` and
  `ci.yml` for ephemeral local/CI containers. They are labelled as such and are not secrets.
* Workflows: top-level `permissions: contents: read`, `pull_request` trigger only, no secrets,
  `persist-credentials: false`, third-party actions pinned by commit SHA, inputs passed via env.
* `.gitignore` excludes venvs, `.pgdata`, results, coverage, `.env*`, audit logs, the pytest temp directory.
* Private filesystem paths: none in tracked files (checked for the user profile path).

## 5. Licensing

Apache-2.0 for original code. No third-party source is vendored or adapted. Dependencies
are MIT/BSD apart from psycopg, an optional, dynamically imported, unmodified LGPL-3.0
dependency (compatible). External validators are installed for benchmarking only and not
redistributed. Benchmark cases are original and synthetic; no external datasets. Upstream
issue found: an agent-sql-guard `PiiDenylist.from_mapping` default bug (documented, not fixed
upstream). See THIRD_PARTY_NOTICES.md.

## 6. Unmet requirement: restricted-function and system-catalog benchmark cases

The maintainer explicitly asked for these cases. Writing them was interrupted twice by an
automated safety classifier, and the assistant was instructed not to produce that content
again, so they are **not** in corpus v1.0.0. Current coverage of that area:

* The rules (`function.*`, `catalog.system_object`) are implemented and run in the default guard.
* Function-policy mechanics are unit-tested with fictitious, policy-configured names
  (`tests/unit/test_function_policy_mechanics.py`).
* The benchmark therefore does **not** measure detection in these two categories. This is
  stated in the README, the methodology, the results document and the release notes.
* Remedy: maintainer-authored case files under `benchmarks/datasets/v1/cases/`, which the
  existing per-case tests and SQLite/PostgreSQL label validation pick up automatically.

## 7. Remains unverified

GitHub Actions on GitHub (all jobs); Docker Compose; Linux execution; Python 3.12; the
optional real-LLM example.
