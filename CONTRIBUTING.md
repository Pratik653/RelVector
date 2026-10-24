# Contributing

Thanks for helping make LLM-generated SQL safer. Bug reports, bypass reports (privately,
see [SECURITY.md](SECURITY.md)), benchmark cases, adapters and documentation are welcome.

## Setup

```bash
git clone https://github.com/Pratik653/SQLGuard_Ninjapy.git
cd SQLGuard_Ninjapy
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Optional: `pip install pgserver` (or `docker compose -f docker/docker-compose.yml up -d` plus
`SQLNINJA_PG_DSN`) to run the PostgreSQL tests. `python scripts/setup_external_adapters.py`
creates the external validators' environments.

## Checks (all must pass)

```bash
ruff check src tests scripts examples
ruff format --check src tests scripts examples
mypy
pytest
python scripts/generate_corpus.py --check
```

Coverage of `sqlguard_ninja` must stay at or above 85% (CI enforces it).

## Adding benchmark cases

1. Add cases to a file in `benchmarks/datasets/v1/cases/` (see
   [BENCHMARK_METHODOLOGY.md](docs/guides/BENCHMARK_METHODOLOGY.md) for the schema and the
   policy semantics labels must follow).
2. Label the **ideal** outcome under the documented semantics, not what the engine currently
   returns. If the engine disagrees, that is a finding: fix the engine, or explain in the PR
   why the semantics should change.
3. `allow` cases must run on the fixture databases; the tests check this for SQLite and
   PostgreSQL.
4. Never relabel an existing case silently. The CI gate fails on label changes, and a
   maintainer must approve them.
5. Matrix-style cases belong in `scripts/generate_corpus.py`; regenerate and commit.

## Adding a rule

Implement the `Rule` protocol (`rule_ids` + `check(ctx) -> Iterable[Finding]`) in
`src/sqlguard_ninja/core/rules/` (or a feature package), add it to `default_rules()`, add
unit tests and corpus cases for the attack class, and document the rule id in
[POLICY_REFERENCE.md](docs/guides/POLICY_REFERENCE.md).

## Adding an external adapter

Add an `ExternalToolSpec` to `benchmarking/adapters.py` and a worker script in
`benchmarking/workers/`. Workers run in the tool's own environment, must not import
`sqlguard_ninja`, and must declare honestly which categories they can express.

## Pull requests

* One topic per PR, with tests. Every bug fix needs a regression test.
* Do not commit real personal data, credentials or production schemas.
* By contributing you agree your contribution is licensed under Apache-2.0.
* Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
