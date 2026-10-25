# Third-party notices

## RelVector (the `relvector` wheel)

RelVector is licensed under Apache-2.0. **It does not vendor or copy third-party source code.**
The one adapted piece is the list of sensitive-column name patterns in
`src/relvector/mapping.py`. It comes from SQLGuard Ninja (`sqlguard_ninja/privacy/suggest.py`),
which has the same authors and the same Apache-2.0 licence.

The packages below are ordinary dependencies, installed by the package manager under their
own licences. Licences were read from installed package metadata on 2026-10-25. Always check
the version you install.

### Runtime dependencies (core install)

| Package | Version tested | Licence | Use |
|---|---|---|---|
| [SQLAlchemy](https://www.sqlalchemy.org/) | 2.1.6 | MIT | Schema inspection, query construction, connections |
| [NumPy](https://numpy.org/) | 2.4.6 | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) | Vector arithmetic |

### Optional extras

| Extra | Package | Version tested | Licence |
|---|---|---|---|
| `local` | sentence-transformers | 6.2.0 | Apache-2.0 |
| `local` (transitive) | torch / transformers | 2.14.1 (CPU) / 5.20.2 | BSD-3-Clause and others (see the package) / Apache-2.0 |
| `postgres` | psycopg (+ psycopg-binary) | 3.3.6 | LGPL-3.0-only |
| `sqlguard` | sqlguard-ninja | 0.7.0 | Apache-2.0 |

psycopg is LGPL-3.0. RelVector does not import it directly; SQLAlchemy loads it at runtime when
a `postgresql+psycopg://` URL is used. It is not modified or bundled.

Embedding models are not part of RelVector. The default local model,
`sentence-transformers/all-MiniLM-L6-v2`, is published under Apache-2.0. Models are downloaded
by sentence-transformers under their own licences; check the licence of any model you configure.

### Development and test tools (not distributed)

pytest (MIT), ruff (MIT), mypy (MIT), build (MIT), twine (Apache-2.0). PostgreSQL tests can
use `pgserver` (not a declared dependency; it bundles PostgreSQL binaries under the
PostgreSQL License) or a PostgreSQL 16 service container in CI.

## Origin of this repository

RelVector's repository began as a copy of SQLGuard Ninja (Apache-2.0, same authors). The
SQLGuard Ninja sources, benchmarks and their third-party notices have been removed from the
working tree. They remain in this repository's git history, and SQLGuard Ninja is developed
and published separately (`pip install sqlguard-ninja`). RelVector uses it only as an optional
dependency.

## GitHub Actions

`actions/checkout`, `actions/setup-python` and `actions/upload-artifact` (MIT, GitHub) are
referenced by commit SHA in the workflows.
