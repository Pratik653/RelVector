# Release checklist — v0.1.0

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Personal email absent from publishable history (metadata + contents) | ✅ | 0 hits; commits use the GitHub-verified noreply address |
| 2 | Repo-local git identity set to noreply | ✅ | `git config --local user.email` |
| 3 | ruff check / format | ✅ | 79 files |
| 4 | mypy --strict | ✅ | 43 source files |
| 5 | Tests, Python 3.11 (Windows) incl. PostgreSQL 16.2 | ✅ | 1,649 passed, 0 failed |
| 6 | Tests, Python 3.13 (Windows) | ✅ | 1,424 passed, 225 PostgreSQL tests skipped (no pgserver build for 3.13) |
| 7 | Coverage (branch) | ✅ | 95% |
| 8 | Corpus reproducibility (`generate_corpus.py --check`) | ✅ | 268 generated cases |
| 9 | Build + `twine check` | ✅ | wheel and sdist PASSED |
| 10 | Clean wheel install smoke test | ✅ | Python 3.13 |
| 11 | pip-audit | ✅ | no known vulnerabilities |
| 12 | gitleaks (history) | ✅ | 6 commits, no leaks |
| 13 | gitleaks (directory) | ✅ | only false positives in git-ignored venvs |
| 14 | Private paths in tracked files | ✅ | none |
| 15 | Licence review | ✅ | THIRD_PARTY_NOTICES.md |
| 16 | Docs examples executable, links resolve | ✅ | tests/unit/test_docs.py |
| 17 | actionlint | ✅ | ci.yml |
| 18 | Restricted-function / system-catalog benchmark cases | ❌ | Not authored (see FINAL_TECHNICAL_AUDIT §6); documented as a limitation |
| 19 | Maintainer publication confirmation | ⏳ | |
| 20 | GitHub repo created, pushed, public | ⏳ | |
| 21 | GitHub Actions run and green | ⏳ | |
| 22 | "Block command line pushes that expose my email" enabled | ⏳ | maintainer setting (no API) |
| 23 | Tag v0.1.0 + GitHub release | ⏳ | |
