## Summary

<!-- Describe what this PR does and why. Include context a reviewer needs to understand the change. -->

## Type of change

- [ ] New feature
- [ ] Bug fix
- [ ] Refactor (no behavior change)
- [ ] Database schema / initialization change
- [ ] Configuration / infrastructure change
- [ ] Tests only

## Module(s) affected

<!-- List affected areas: api, web, agent, db, deps, common or ci. -->

## Author checklist

Complete every item before requesting review.
Mark checks unrelated to this change as N/A with a reason; list commands and actual results.

- [ ] `python scripts/check_repository.py` passes
- [ ] `python scripts/check_git.py --range origin/develop..HEAD` passes
- [ ] API changes: `uv sync --project api --frozen` and `uv run --project api pytest -c api/pyproject.toml` pass
- [ ] Web changes: `npm --prefix web ci`, `npm --prefix web run typecheck` and `npm --prefix web run build` pass
- [ ] Container / service setup changes: `docker compose config --quiet` and `docker compose up --build --wait` pass
- [ ] Configuration changes are documented in `.env.example` and README.md where relevant
- [ ] CHANGELOG.md is updated; no credentials or private datasets are included
- [ ] CI passes and CodeRabbit reviewed the latest commit; every actionable finding is fixed or answered

API tests must not make live OpenAI requests.
The billable OpenAI connectivity smoke check is separate and runs only when explicitly requested.

## Database migration checklist

Complete only when this PR changes PostgreSQL/pgvector schema, extensions or database initialization.

- [ ] Fresh-database setup is verified; changes to `scripts/init_db.sql` account for its new-volume-only behavior
- [ ] Any upgrade needed for an existing database is documented and preserves existing data
- [ ] Compatibility, rollback/recovery and pgvector model/dimension implications are documented where relevant

The project currently uses a PostgreSQL initialization script, not a versioned migration runner.
Do not assume editing that script upgrades an existing database or requires deleting its volume.

## Reviewer checklist

- [ ] Changes follow existing FastAPI/Python and Next.js/TypeScript patterns; planned features are not described as implemented
- [ ] API keys remain server-side; web bundles and health probes do not expose or consume OpenAI credentials
- [ ] No cyclic dependencies introduced between modules
- [ ] New endpoints are covered by integration or unit tests

## Related issues

Closes #ISSUE_NUMBER
