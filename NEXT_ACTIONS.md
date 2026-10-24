# Next actions

_Updated 2026-10-24. On resume: read IMPLEMENTATION_STATUS.md, run
`.venv/Scripts/python -m pytest -q` and `git log --oneline`, then continue from the top._

## Release (in progress)

1. ✅ Email privacy: history rewritten to the verified noreply address (local backup branch
   `backup/pre-email-rewrite` must never be pushed).
2. ⏳ Maintainer confirms publication (summary prepared).
3. Then: `gh repo create Pratik653/SQLGuard_Ninjapy --public`, push `main` only, watch CI,
   fix failures, tag `v0.1.0`, publish release notes from docs/releases/v0.1.0.md, enable
   private vulnerability reporting, Dependabot and branch protection; record SHAs and run
   URLs in RELEASE_CHECKLIST.md.

## Engineering backlog

3. Restricted-function and system-catalog benchmark categories (maintainer-authored cases).
4. Independent held-out corpus written by people outside the project.
5. Lineage-aware aggregate-only checks; tenant predicate push-down into CTEs.
6. Function allowlist presets for PostgreSQL/SQLite analytics.
7. Propose the agent-sql-guard `PiiDenylist.from_mapping` default fix upstream.
