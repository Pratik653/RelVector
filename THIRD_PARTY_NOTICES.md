# Third-party notices

SQLGuard Ninja is licensed under Apache-2.0. **It does not vendor or copy third-party source
code.** The projects below are used as ordinary dependencies, installed by the package
manager under their own licences. Licences were read from installed package metadata on
2026-10-24. Always check the version you install.

## Runtime dependencies (core install)

| Package | Version tested | Licence | Use |
|---|---|---|---|
| [sqlglot](https://github.com/tobymao/sqlglot) | 30.24.0 | MIT | SQL parsing, dialects, scope analysis, column qualification |
| [pydantic](https://github.com/pydantic/pydantic) (+ pydantic-core) | 2.14.1 | MIT | Policy/config schema validation |
| [PyYAML](https://pyyaml.org/) | 6.0.3 | MIT | Policy and dataset files |

## Optional extras

| Extra | Package | Version tested | Licence |
|---|---|---|---|
| `langchain` | langchain-core | 1.7.0 | MIT |
| `langgraph` | langgraph | 1.2.17 | MIT |
| `fastapi` | fastapi / starlette | 0.162.0 / 1.9.0 | MIT / BSD-3-Clause |
| `postgres` | psycopg (+ psycopg-binary) | 3.3.6 | LGPL-3.0-only |

psycopg is LGPL-3.0. SQLGuard Ninja only imports it at runtime when the `postgres` extra is
installed. It is not modified or bundled, which is compatible with distributing SQLGuard Ninja
under Apache-2.0.

## Development and test tools (not distributed)

pytest (MIT), pytest-cov (MIT), hypothesis (MPL-2.0), httpx (BSD-3-Clause), ruff (MIT),
mypy (MIT), build (MIT). `pgserver` is optionally used for local PostgreSQL tests. It is not a
declared dependency, and its package metadata on PyPI does not declare a licence. It bundles
PostgreSQL binaries (PostgreSQL License).

## External validators used for benchmarking only

Installed into isolated virtual environments by `scripts/setup_external_adapters.py`, never
redistributed:

| Tool | Version | Licence | Source |
|---|---|---|---|
| sql-guardrail | 0.5.2 | MIT | https://github.com/nickusevich/sql-guardrail |
| agent-sql-guard | 0.2.0 | Apache-2.0 declared in `pyproject.toml`; the repository contains no LICENSE file | https://github.com/sakura-sky/sql-guard |
| sqlguard (krish2105) | git 62327f2 | MIT | https://github.com/krish2105/sqlguard |

## GitHub Actions

`actions/checkout`, `actions/setup-python` and `actions/upload-artifact` (MIT, GitHub) are
referenced by commit SHA in the workflows and the composite action.

## Data

All benchmark data and fixture rows are synthetic and were written for this project. Card
numbers are the published test PAN `4111111111111111`. Emails use the reserved
`example.com`/`example.org` domains. No third-party datasets were used.
