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
| 19 | Maintainer publication authorization | ✅ | given in chat (GitHub + PyPI) |
| 20 | GitHub repo created, pushed, public | ✅ | https://github.com/Pratik653/SQLGuard_Ninjapy — anonymous API: public, Apache-2.0 detected, `main` only |
| 21 | Public commit emails | ✅ | all commits: noreply address only (checked via the public API) |
| 22 | GitHub Actions, first run | ❌→fixed | run 40088280743: test matrix failed on an untracked results directory (`.gitignore` too broad); fixed in 08496a2 |
| 23 | GitHub Actions, all 12 jobs green | ✅ | run 40089006916 on 08496a2: tests 3.11/3.12/3.13 × Linux/Windows (1,423 passed, 3 skipped — external-tool tests, 92.87% coverage without PostgreSQL), PostgreSQL service 225 passed, Docker Compose 225 passed, gate, external validators, package build |
| 24 | Topics, private vulnerability reporting, Dependabot alerts, `pypi` environment | ✅ | configured via GitHub API |
| 25 | "Block command line pushes that expose my email" | ⏳ | maintainer setting (no API) |
| 26 | PyPI pending trusted publisher | ⏳ | maintainer action on pypi.org |
| 27 | Tag v0.1.0 + GitHub release + PyPI publish | ⏳ | |
| 28 | Fresh install from PyPI + smoke tests | ⏳ | |
