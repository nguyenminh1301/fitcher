# Phase 13: App state and first-run setup

## Goal

Give the application a place to keep what a user chooses, so that nothing requires editing `.env`: a SQLite app state with encrypted secrets, numbered schema changes that upgrade an existing volume, and the first-run setup shell that later phases fill with their steps (DECISIONS §2, §3, §15).

## Scope

- App state file with typed settings, encrypted secrets and the setup state.
- Numbered schema changes for the app state and for ClickHouse, applied by one command and recorded in a version table.
- Setup API and the `/setup` page with its first step (individual or team). The choice is stored; it changes sign-in only in Phase 15.
- `FITCHER_DATA_DIR` as the single root of persistent files.

## Out of scope

- Model providers (Phase 14), sign-in (Phase 15), sources (Phase 17), the documents switch (Phase 20).
- Moving conversations or logs out of ClickHouse.
- A general settings page: each later phase adds the page for its own settings.

## Prerequisites

- Phases 0 to 12 on `develop`.

## Deliverables

```text
apps/api/app/state/db.py             # one SQLite connection per thread, WAL, foreign keys on, single-writer lock
apps/api/app/state/changes/          # 0001_settings.sql, 0002_secrets.sql, 0003_setup.sql
apps/api/app/state/migrate.py        # applies pending app-state changes inside one transaction each
apps/api/app/state/secrets.py        # AES-256-GCM with the instance key; set, has, last four, delete; never a plain read endpoint
apps/api/app/state/settings.py       # typed get/set by group and key
apps/api/app/state/setup.py          # step states and completion
apps/api/app/api/setup.py            # setup endpoints
infra/clickhouse/changes/            # the initdb files renumbered as changes, plus later ones
jobs/migrate.py                      # applies app-state and ClickHouse changes; replaces jobs.apply_log_schema
apps/web/app/setup/                  # setup shell and the "Who uses this instance" step
```

## Tasks

1. **App state store (test first).** Open `<FITCHER_DATA_DIR>/app.db` in WAL mode with a busy timeout; writes go through one lock. Tests use a temporary directory.
2. **Schema changes (test first).** A change is a numbered SQL file. `migrate` applies the pending ones in order, records each in `schema_changes` and refuses to run when the store records a number higher than the code knows. The same runner applies `infra/clickhouse/changes/` to ClickHouse, recorded in `data_meta.schema_changes`; every ClickHouse change is idempotent because ClickHouse has no transactional DDL.
3. **Existing volumes.** The current `infra/clickhouse/initdb` files become the first ClickHouse changes without altering their statements, so a volume created before this phase is recorded as up to date instead of being changed. `jobs.apply_log_schema` becomes a thin alias of `jobs.migrate` and its documentation is updated.
4. **Secrets (test first).** The instance key is `FITCHER_SECRET_KEY` (base64, 32 bytes) or a key generated on first use in `<FITCHER_DATA_DIR>/secret.key` with mode 0600. A secret is stored as nonce plus ciphertext with its name as associated data. The module exposes no function that returns a secret to an API handler; callers that need the value (the LLM gateway in Phase 14) receive it through a narrow interface. A wrong or missing key fails with a clear error, never with an empty secret.
5. **Settings and setup state (test first).** Settings are typed per group. The setup state records each step as `pending`, `done` or `skipped` and whether setup is complete.
6. **Setup API (test first).** Endpoints of the Contracts section. Until Phase 15 they require the `admin` role of the existing sign-in.
7. **Setup page.** `/setup` shows the steps as a list with the current one open; this phase implements the first step only and shows the others as coming with their phase hidden from the user (a step that has no implementation yet is not listed). An incomplete setup redirects an admin to `/setup`; other users see a notice that the instance is being set up.
8. **Documentation.** `infra/README.md` and `jobs/README.md` describe the data directory, the secret key and `jobs.migrate`; `.env.example` gains `FITCHER_DATA_DIR` and `FITCHER_SECRET_KEY`.

## Contracts

- `GET /setup/status` -> `{mode: "individual"|"team"|null, steps: [{id, state}], complete}`.
- `PUT /setup/mode` with `{mode}`; `POST /setup/steps/{id}/skip`; `POST /setup/complete`.
- Environment: `FITCHER_DATA_DIR` (default `/data`; the development Compose file mounts a named volume there), `FITCHER_SECRET_KEY` (optional).
- Tables: app state `schema_changes`, `settings`, `secrets`, `setup_steps`; ClickHouse `data_meta.schema_changes`.

## Verification

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck && npm --prefix apps/web run test && npm --prefix apps/web run build
docker compose config --quiet && docker compose up --build --wait
docker compose run --rm jobs python -m jobs.migrate          # twice: the second run applies nothing
python scripts/check_repository.py
```

A volume created before this phase must start, report every existing change as applied and lose no row.

## Definition of done

- A fresh volume and a pre-existing volume both reach the same recorded schema version with `jobs.migrate`.
- A stored secret is unreadable in `app.db` with `strings`, survives a restart and cannot be fetched through any endpoint.
- A new instance opens on `/setup`; choosing a mode is stored and shown on reload.

## Risks and open questions

- SQLite on a network file system can corrupt under concurrent access. Default: document that the data volume must be a local disk.
- Losing `secret.key` makes stored secrets unreadable. Default: the setup tells the user that the data volume is the backup unit, and Phase 21 adds the backup command.

## Branch and PR split

`feat/api/add-app-state-and-setup`: one PR for the store, changes and secrets; one for the setup API and page.
