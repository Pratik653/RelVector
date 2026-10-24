# Next actions

_Updated 2026-10-24. On resume: read IMPLEMENTATION_STATUS.md, run
`.venv/Scripts/python -m pytest -q` and `git log --oneline`, then continue from the top._

## Blocked on the maintainer

1. **Publication approval** (required before anything leaves this machine):
   * Confirm GitHub owner/account (docs assume `Pratik653`), repository name
     `SQLGuard_Ninjapy`, visibility public, licence Apache-2.0.
   * Decide the commit author email: local commits use the global git email. Options:
     rewrite to the GitHub noreply address before the first push, or keep it.
   * Choose a publication route: `gh` is not installed (it could be installed with winget
     and authenticated by the maintainer), or use the authenticated browser session.
2. After publication: watch the first CI run and fix anything Linux/3.12/3.13-specific, then
   tag `v0.1.0`, publish release notes from docs/releases/v0.1.0.md, enable private
   vulnerability reporting, Dependabot alerts and branch protection, and add CODEOWNERS for
   `benchmarks/` and `.github/`.

## Engineering backlog

3. Restricted-function and system-catalog benchmark categories (maintainer-authored cases).
4. Independent held-out corpus written by people outside the project.
5. Lineage-aware aggregate-only checks; tenant predicate push-down into CTEs.
6. Function allowlist presets for PostgreSQL/SQLite analytics.
7. Propose the agent-sql-guard `PiiDenylist.from_mapping` default fix upstream.
