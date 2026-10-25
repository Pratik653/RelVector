# Contributing

Bug reports, focused fixes, documentation and well-scoped features are welcome. Please open
an issue before starting larger changes. Report vulnerabilities privately (see
[SECURITY.md](SECURITY.md)).

## Setup

```bash
git clone https://github.com/Pratik653/RelVector.git
cd RelVector
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## Checks (all must pass)

```bash
ruff check src/relvector tests/relvector examples/relvector
mypy
pytest
```

* PostgreSQL tests (`tests/relvector/test_postgres.py`) run against a throwaway server. Set
  `RELVECTOR_PG_DSN` to an admin DSN, or `pip install pgserver` for an embedded one. They
  skip otherwise. Each test creates and drops its own database. Never point
  `RELVECTOR_PG_DSN` at a database you care about.
* The real-model smoke test runs only if `sentence-transformers` and
  `all-MiniLM-L6-v2` are already installed and cached. The test suite never downloads models.

## Guidelines

* Every bug fix comes with a regression test. Use small synthetic data only: no real personal
  data, credentials or production schemas.
* Keep the core dependencies minimal (SQLAlchemy, NumPy). Anything heavier goes behind an
  optional extra and is imported lazily.
* RelVector only ever reads the source database. New code must keep extraction to
  SQLAlchemy Core `SELECT` statements with bound parameters.
* Update the README and `docs/relvector/architecture.md` when behaviour or limitations change.
