# Implementation status

_Updated 2026-10-24. Evidence only: a column is ticked only when it has been verified by
tests or files in this repository._

Legend: ✅ done · 🟡 partial · ⬜ not started

| Workstream / component | Planned | In progress | Implemented | Tested | Integrated | Documented | Release-ready |
|---|---|---|---|---|---|---|---|
| Core engine (analysis, rules, guard) | ✅ | ✅ | ✅ | ✅ | ✅ | 🟡 ADRs only | ⬜ |
| WS1 Benchmark: corpus | ✅ | ✅ | 🟡 2 of ~16 categories | ✅ per-case pytest | ⬜ | ⬜ | ⬜ |
| WS1 Benchmark: runner / metrics / adapters / compare | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| WS2 Agent checkpoint, LangChain, LangGraph, FastAPI | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| WS3 Privacy policy pack | ✅ | ✅ | ✅ | ✅ unit | ✅ in Guard | ⬜ | ⬜ |
| WS4 Static cost analysis | ✅ | ✅ | ✅ | 🟡 unit, 71% cov | ✅ in Guard | ⬜ | ⬜ |
| WS4 PostgreSQL EXPLAIN inspector | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| WS5 CI regression action | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |
| CLI | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ |

## Latest verification (local, Windows 11, Python 3.11.9)

* `ruff check src tests` — pass. `ruff format --check` — pass. `mypy` (strict) — pass, 23 files.
* `pytest` — **223 passed**, 0 failed. Branch coverage of `sqlguard_ninja`: **88%**.
  Lowest-covered modules: `core/rules/functions.py` (64%), `query_cost/static.py` (71%),
  `core/rules/catalog.py` (71%).
* Benchmark corpus: 2 case files, every case checked by `tests/security/test_corpus_native.py`;
  every ALLOW case for SQLite executes on the fixture DB (`tests/integration/...`).

## Defects found by the test suite and fixed (each has a regression test)

1. Unknown column in the select list was ALLOWED: after qualification `password AS password`
   matched its own alias and was exempted as an `ORDER BY` alias reference.
2. `Guard.validate` raised `UnicodeEncodeError` on a lone surrogate (found by Hypothesis);
   now denied as `parse.invalid_characters`.
3. Dataset loader silently cleared an explicit rejection reason on an `allow` case instead of
   rejecting the inconsistent label.
4. Benchmark label error: `FMT-010` (parenthesised top-level SELECT) was labelled allow for
   SQLite, but SQLite rejects that syntax; it is now PostgreSQL-only.
5. Generic-disclosure mode produced ungrammatical messages and compared enums by identity.

## Open gap

The restricted-function and system-catalog benchmark categories are **not authored**. Writing
those cases was interrupted twice by an automated safety classifier and I cannot produce them.
The rules themselves are implemented and smoke-tested. They need corpus cases, added by a
maintainer; `tests/security/test_corpus_native.py` picks them up automatically.
