# Phase 6: RBAC and auth

## Goal

Enforce permissions at all three layers of DECISIONS §9, generated from `policies.yaml` alone: retrieval filtering, the guard allowlist and, as the real boundary, ClickHouse roles, grants, row policies and aggregate-only views.

## Scope

- Keycloak realm with pack roles and sample users.
- Policy compiler output: ClickHouse roles, per-role users, grants, row policies, settings profiles, aggregate-only views, guard allowlists and index `allowed_roles`.
- Role-aware retrieval, guard and execution; `gate` deny branch with audit.

## Out of scope

- JWT verification in HTTP requests (Phase 7); this phase passes the role explicitly (CLI flag, tests).
- Admin views of audit data (Phase 12).

## Prerequisites

- Phases 2-5: compiler, graph, eval, `agent_logs.audit` table.

## Deliverables

```text
packs/_schema/policies.schema.json           # extended
packs/ecommerce_twin/policies.yaml           # at least three roles, one row-filtered, one aggregate-only
apps/api/app/packs/policy_compiler.py        # policies -> ClickHouse DDL + allowlists
infra/keycloak/realm-finch.json              # roles and sample lab users
apps/api/app/agent/nodes/gate.py
apps/api/tests/integration/test_role_matrix.py
```

## Tasks

1. **Policy model (test first).** Per role: datasets with column lists, optional row filter expression, optional aggregate-only spec (dimensions, measures, minimum group size k). Validation: referenced datasets/columns exist; row filters parse as sqlglot boolean expressions over the dataset's columns.
2. **DDL generation (test first, golden files).** For each role: `CREATE ROLE IF NOT EXISTS`, `GRANT SELECT(<columns>) ON marts.<table>`, `CREATE ROW POLICY ... USING <filter> TO <role>`, aggregate-only views `marts.agg_<role>_<dataset>` with `HAVING count() >= k` and grants on the view only, and a settings profile. Managed objects carry a naming prefix. The compiler reconciles to the desired state: it discovers managed objects by prefix in `system.grants` (grants), `system.row_policies` (row policies), `system.tables` in `marts` (aggregate views), `system.roles` (roles) and `system.users` (users), revokes every grant and drops every row policy, view, role and user that the policy no longer contains, then applies the missing ones. Policy-shrink tests remove a column, a dataset, an aggregate view, a role and a user, and prove each removed object is gone and a previously allowed query is denied by ClickHouse after `compile_pack`.
3. **Settings profile.** Use `readonly = 2` with constraints so the agent can set `log_comment` and per-query limits but cannot raise `max_execution_time`, `max_result_rows` or `max_memory_usage` above the profile maximums; `readonly = 1` would reject `log_comment`.
4. **Users and mapping.** One ClickHouse user per Keycloak role (`agent_<role>`), passwords from env; the api holds credentials and never puts them in prompts.
5. **Apply.** `compile_pack` applies the DDL as admin, idempotently, after metric checks.
6. **Role-aware layers.** Retrieval filters every index by `allowed_roles`; guard loads the per-role allowlist; execute connects as the role's user.
7. **gate deny branch.** No permitted dataset or metric -> deny with an understandable message and an `audit` DENY row; guard policy rejections also write DENY. ALLOW records the gate and guard authorization of a SQL attempt, not a successful execution; ClickHouse rejections and runtime failures are recorded in `sql_runs` with their error and attempt number, and a ClickHouse access-denied error also writes a DENY row. Denials never enter the retry loop.
8. **Keycloak realm.** Realm roles equal to policy roles; sample users are defined without credentials in the tracked realm file; `jobs/set_lab_passwords.py` sets their passwords from local `.env` values through the Keycloak admin API; client scopes put roles into the access token.
9. **Matrix tests and eval.** Integration tests run each role against each dataset directly on ClickHouse, with the guard bypassed, and assert the expected allow, deny, filtered-rows or aggregate-only behaviour. Eval cases of category `unauthorized` become active.

## Contracts

- `policies.yaml` schema; generated allowlist shape `{role: {dataset: [columns]}}`.
- Audit row: `trace_id, ts, user_id, role, decision, reason, datasets, columns`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
uv run --project apps/api pytest -c apps/api/pyproject.toml -m integration    # needs running ClickHouse
docker compose run --rm api python -m jobs.compile_pack --pack ecommerce_twin
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

## Definition of done

| DoD item | Proof |
|---|---|
| Role x dataset matrix passes | Integration test report |
| Over-permission SQL is blocked by ClickHouse with the guard disabled | Matrix tests execute raw SQL as each role user |
| Eval gains deny questions | Active `unauthorized` cases in the report |

## Risks and open questions

1. **Integration tests in CI.** Default: add a ClickHouse service container to the CI API job for `-m integration`; unit tests remain runnable without it.
2. **Users with several roles.** Default: the request carries one active role; a user holding several picks one (UI selector in Phase 9), otherwise the first pack role in policy order.
3. **Aggregate-only granularity.** Default: one view per role and dataset with the dimensions listed in the policy.
4. **Sample credentials.** Lab-user passwords are never committed; they come from the developer's `.env` and are never reused elsewhere.

## Branch and PR split

- `feat/pack/compile-access-policies`: tasks 1-5.
- `feat/agent/enforce-role-permissions`: tasks 6-7, 9.
- `feat/infra/import-keycloak-roles`: task 8.
