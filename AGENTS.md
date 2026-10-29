# Repository instructions

## Scope

- fitcher includes a local Next.js/FastAPI/PostgreSQL foundation; data analysis, LangGraph, DuckDB, SSE and chat/chart features remain planned. Read README.md for current status and available commands.
- Implement only the requested scope; do not scaffold application code or add dependencies speculatively.
- Write code identifiers, documentation and GitHub content in English; chat with the owner in Vietnamese.
- Read `.agents/rules/git_workflow.md` before branches, commits or PRs; `.github/git-policy.json` is the executable type/scope allowlist.
- Keep OpenAI credentials server-side, and exclude secrets, local Parquet/database files and scratch artifacts from commits.

## Working rules

- Inspect current files and Git status first, and preserve unrelated user changes.
- Use the main checkout; do not create implementation worktrees.
- Work on a focused branch from `develop` and open a PR into `develop`; the owner's deliberate direct push to `main` is the documented exception.
- For small, clear documentation/configuration changes, proceed directly; no separate approval rounds, design documents or application tests are required.
- Use one agent unless delegation is explicitly requested.
- Reuse existing patterns; search with `rg` and read targeted files.
- Preserve Windows/PowerShell and Linux support without changing global toolchains.

## Verification and delivery

- Run `python scripts/check_repository.py`; lint the relevant commit range with `python scripts/check_git.py --range <base>..HEAD`.
- Validate GitHub Actions changes with actionlint; use the CI result when the tool is unavailable locally.
- Update CHANGELOG.md for each logical change; commits are one conventional line, without bodies or attribution.
- Report actual verification results and unavailable checks; do not claim an unrun application test passes.
- CodeRabbit must review the latest PR commit and all actionable findings must be fixed or answered before finalizing a PR.
- Do not merge, enable auto-merge, rewrite published history, publish the repository or contact other people without authorization.
