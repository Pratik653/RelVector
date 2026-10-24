# Next actions

_Updated 2026-10-24. On resume: read IMPLEMENTATION_STATUS.md, run
`.venv/Scripts/python -m pytest -q` and `git log --oneline`, then continue from the top._

## Release

v0.1.0 is released on GitHub and PyPI and verified (see RELEASE_CHECKLIST.md).

## Post-release maintenance (next)

1. 0.1.1: make README links absolute so they work on the PyPI page (relative links break there).
2. Maintainer: enable "Block command line pushes that expose my email" (GitHub → Settings → Emails);
   add branch protection on `main` requiring the CI checks; add CODEOWNERS for `benchmarks/` and `.github/`.
3. Review Dependabot PRs; keep actions SHA-pinned.
4. Delete the local `backup/pre-email-rewrite` branch once you no longer need the old history (it was never pushed).

## Engineering backlog

3. Restricted-function and system-catalog benchmark categories (maintainer-authored cases).
4. Independent held-out corpus written by people outside the project.
5. Lineage-aware aggregate-only checks; tenant predicate push-down into CTEs.
6. Function allowlist presets for PostgreSQL/SQLite analytics.
7. Propose the agent-sql-guard `PiiDenylist.from_mapping` default fix upstream.
