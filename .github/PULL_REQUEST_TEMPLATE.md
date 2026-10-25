## What and why

<!-- One topic per PR. Link issues. -->

## Checklist

- [ ] Tests added or updated (every bug fix has a regression test)
- [ ] `ruff check src/relvector tests/relvector examples/relvector`, `mypy` and `pytest` pass locally
- [ ] The source database is still only read (SQLAlchemy Core `SELECT`, bound parameters)
- [ ] README / `docs/relvector/architecture.md` updated if behaviour or limitations changed
- [ ] No real personal data, credentials or production schemas
