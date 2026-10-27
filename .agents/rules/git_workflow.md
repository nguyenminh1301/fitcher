# Git workflow

## Branch roles

- `develop`: default development/integration branch; never commit implementation work directly here.
- `main`: production branch; the repository owner may deliberately push directly without a PR.
- Other contributors use a branch from updated `develop` and a PR targeting `develop`.
- Release promotion from `develop` to `main` requires the owner's approval; use a release PR or the owner's deliberate direct push.
- The initial governance bootstrap updates `main` and creates `develop` at the same commit; subsequent work follows the normal branch workflow.
- Use the main checkout, not Git worktrees.

## Naming

Branches use `<type>/<scope>/<short-description>`.
Branch types are `feat`, `fix` and `chore`; scopes come from `.github/git-policy.json`; descriptions are lowercase hyphen-separated words.
Examples: `feat/agent/generate-read-only-sql`, `fix/api/stop-cancelled-query`, `chore/ci/update-workflow-checks`.

Commits and PR titles use `<type>(<scope>): <subject>`.
The executable allowlist is `.github/git-policy.json`:

- Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`, `perf`, `ci`.
- Scopes: `web`, `api`, `agent`, `db`, `deps`, `common`, `ci`.
- Subject starts with a lowercase English letter.
- Entire message is at most 80 characters; target 72.
- Exactly one line, without a body, rationale, validation notes, footers, co-author trailers or agent signatures.
- Describe the concrete change; do not use private task IDs or attempt numbers as the name.

Examples: `feat(agent): generate validated sql`, `docs(common): explain local setup`, `ci(ci): lint pull request titles`.
The initial README commit predates these rules; enforce the policy on new commits without rewriting existing history.

## Commit granularity

Each commit is a complete, independently reviewable working change.
Do not combine unrelated fixes, and do not split one change into broken intermediate commits.
Update CHANGELOG.md; rationale and verification belong in the PR description.
Do not force-push or rewrite published history unless explicitly requested.

## Pull requests

Start from updated `develop`, use a focused branch, and target `develop` for normal work.
Ready PRs require relevant CI and a CodeRabbit review of the latest commit with every actionable finding fixed or answered.
Drafts are not reviewed automatically.
An unavailable, skipped or rate-limited CodeRabbit run is not a completed review.
Stop after three review/fix rounds and report unresolved findings to the owner.
No automatic merge or auto-merge is authorized by the review loop.
CODEOWNERS names only the owner; the owner does not need to approve their own PR.

Keep PRs at most 1000 changed lines where practical and below 100 changed files.
Size labels are advisory, including `size/XL` above 2000 lines; they do not block merge.
Written rules and CODEOWNERS do not enforce branch protection; repository settings must be configured separately if enforcement is desired.

## Local checks

```bash
python scripts/check_repository.py
python scripts/check_git.py --range origin/develop..HEAD
python scripts/check_git.py --title "chore(common): update project setup"
```
