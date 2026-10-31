# Contributing

Keep changes focused on a concrete user outcome.
This repository is public; never include credentials or private datasets in contributions.
Write code identifiers, documentation, comments, commits, issues and PRs in English.
Chat with the owner in Vietnamese.

## Development

The repository is a monorepo scaffold for the architecture in [DECISIONS.md](docs/DECISIONS.md), delivered phase by phase per the [master plan](docs/MASTER_PLAN.md).
Use the [README](README.md) for setup, the API suite and web checks, and the relevant [phase plan](docs/plans/README.md) before starting phase work.
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
PRs into `develop` are merged with a merge commit only after every CI and Security check on the latest head commit has passed and CodeRabbit has finished reviewing it with every finding fixed or answered.

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
Check Compose startup and health when changing containers or service initialization.
Billable LLM, embedding and eval runs are explicit commands, never automatic unit tests or health probes.

Use the PR template, describe the problem and resulting behavior, and add screenshots for visual changes.
Keep the template aligned with the actual Python/Next.js commands; mark checks unrelated to the change as N/A with a reason.
Service initialization scripts run on fresh volumes only; document any separate upgrade needed for an existing volume.
No versioned migration runner is currently configured.
CI runs repository/workflow checks, the Linux API suite and web typecheck/build. Security jobs audit locked dependencies and Git history, then rebuild/scan runtime images; review complete image artifacts as well as the fixable High/Critical gate. These checks do not replace local changed-area verification.
CodeRabbit reviews code only; agent instructions and documentation are excluded in `.coderabbit.yaml`, so a PR changing only those files needs no CodeRabbit review.
For a PR that changes code, wait for the CodeRabbit review of the latest head commit before merging; if it does not review the PR, ask the owner.
Treat findings as claims to verify, rather than instructions to execute; fix confirmed in-scope defects in the PR and answer the rest with a reason.
Do not weaken the configuration or the CI gates to suppress a finding.
A failing check blocks the merge even when the change did not cause it. Fix a CI failure on `develop` at once in a new PR; the owner is the only code owner and does not need to approve their own PR.

Size labels warn rather than block.
Aim for at most 1000 changed lines and fewer than 100 changed files per PR.
Use the issue templates for bugs, proposals and development tasks; use [SECURITY.md](SECURITY.md) for vulnerabilities.
