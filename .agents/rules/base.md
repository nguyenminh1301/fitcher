---
trigger: always_on

description: Always active. Sets communication, scope, repository boundaries and verification standards for fitcher.
---

# Base Rule - fitcher

## 1. Communication and scope

- Chat with the owner in Vietnamese.
- Write code identifiers, comments, documentation and GitHub content in English.
- fitcher includes a local Next.js/FastAPI/PostgreSQL foundation with pgvector.
- Data analysis, LangGraph, DuckDB, SSE and chat/chart features remain planned; read README.md for current status and available commands.
- Implement only the requested scope; do not add speculative application code, dependencies or abstractions.

## 2. Working standards

- Read `workspace.md` and the current task's progress before acting.
- Apply `naming.md` to every tracked name and explanation; do not make committed artifacts depend on private task context.
- Inspect applicable rules, current files and Git state; preserve unrelated user changes.
- Use the main checkout, never Git worktrees.
- Load `git_workflow.md` before branches, commits or PRs.
- Use one agent unless delegation is explicitly requested.
- For small, clear documentation/configuration edits, proceed directly without separate design approval or application-test ceremony.
- Preserve Windows/PowerShell and Linux support without changing global toolchains.

## 3. Verification and security

- Run `python scripts/check_repository.py` and the applicable `python scripts/check_git.py --range <base>..HEAD` checks.
- Run actionlint for GitHub Actions changes; report an unavailable check explicitly.
- Keep secrets server-side and exclude local datasets, database files and scratch artifacts from Git.
- Report actual command results; do not claim unrun application tests or absent features are verified.
- Update CHANGELOG.md for each logical change.
- Follow the PR review requirements in `git_workflow.md`; do not merge, enable auto-merge, rewrite published history, change repository visibility or contact other people without authorization.

## 4. Instruction mirrors

`.agents/` and `.claude/` carry identical rule and skill content for their respective entry points.
Update both copies in the same change; do not maintain divergent policies.
