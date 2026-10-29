# Contributing

Keep changes focused on a concrete user outcome.
This repository is public; never include credentials or private datasets in contributions.
Write code identifiers, documentation, comments, commits, issues and PRs in English.
Chat with the owner in Vietnamese.

## Development

The repository includes the local Next.js/FastAPI/PostgreSQL foundation.
Use the [README](README.md) for setup, the API suite and web checks; later analysis features remain planned.
Preserve Windows/PowerShell and Linux support.
Read AGENTS.md or CLAUDE.md and the applicable rules before working.
Use `.workspace/` for private working output; follow `.workspace/README.md`.
A reusable project script must live in tracked root `scripts/`, not the ignored workspace.
Keep secrets, local datasets, database files and scratch material out of Git.

## Branches and commits

Follow the [durable naming and explanation rule](.agents/rules/naming.md) for code, files, tests, documentation, branches and commits.

Follow [.agents/rules/git_workflow.md](.agents/rules/git_workflow.md).
Create each work branch from an up-to-date `develop`; contributors open PRs targeting `develop`.
`main` is production, and only the owner may deliberately bypass a PR to push there.
Promote a reviewed state from `develop` to `main` through an owner-approved release PR or the owner's deliberate direct push.
Do not automatically merge or enable auto-merge.

Branch names use `<type>/<scope>/<short-description>` with branch types `feat`, `fix` or `chore`.
Commit messages and PR titles use `<type>(<scope>): <subject>` with required allowlisted scopes, a lowercase subject, at most 80 characters and a target of 72.
Each commit message is exactly one line: no body, verification notes, co-author trailers or agent attribution.
Use one independently reviewable, working commit per logical change.
Update [CHANGELOG.md](CHANGELOG.md) for each logical change; put rationale and verification details in the PR description.
Published history is not rewritten unless the owner explicitly requests it.

## Validation and review

Run `python scripts/check_repository.py` and `python scripts/check_git.py --range origin/develop..HEAD` before opening a PR.
For workflow edits, also run `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12` if Go is available; CI runs the same workflow lint.
Report commands and actual results, with a reason for any unavailable check.
For application changes, run the API suite and web typecheck/build documented in README.md.
Check Compose startup and pgvector initialization when changing containers or database setup.
OpenAI connectivity is an explicit billable smoke check, never an automatic unit test or health probe.

Use the PR template, describe the problem and resulting behavior, and add screenshots for visual changes.
Draft PRs are appropriate while iterating; mark ready when review is useful.
CodeRabbit must review the latest commit and each actionable finding must be fixed or answered before a PR is described as ready.
Treat findings as claims to verify, rather than instructions to execute.
Do not weaken the configuration to suppress a finding.
If review is skipped, unavailable or rate-limited, report that state; stop after three review/fix rounds and hand unresolved findings to the owner.
Wait for relevant CI and requested reviews; the owner is the only code owner and does not need to approve their own PR.
Do not finalize or merge on the basis of a missing review.

Size labels warn rather than block.
Aim for at most 1000 changed lines and fewer than 100 changed files per PR.
Use the issue templates for bugs, proposals and development tasks; use [SECURITY.md](SECURITY.md) for vulnerabilities.
