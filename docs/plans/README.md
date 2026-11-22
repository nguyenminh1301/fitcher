# Phase plans

One plan per phase of the [master plan](../MASTER_PLAN.md). Every plan follows [DECISIONS.md](../DECISIONS.md); where a plan and DECISIONS disagree, DECISIONS wins and the plan is corrected.

These plans fix scope, deliverables, task order, verification and open questions. They stop at task design: when a phase starts, its branch begins with a code-level, test-first task plan derived from the phase plan, and the open questions listed here are answered by the owner before the affected task starts. Settled answers are written back into DECISIONS §14 or the phase plan in the same change.

## Template

Every phase plan has these sections:

| Section | Contents |
|---|---|
| Goal | One paragraph: the outcome the phase delivers |
| Scope / Out of scope | What the phase includes and what it deliberately leaves to later phases |
| Prerequisites | Phases and artifacts that must already exist |
| Deliverables | File tree and components the phase adds or changes |
| Tasks | Ordered, independently reviewable tasks; tests are written before code |
| Contracts | Interfaces, schemas and configuration keys introduced or changed |
| Verification | Commands and the result that counts as passing |
| Definition of done | The master plan DoD, with the check that proves each item |
| Risks and open questions | Decisions the owner must make, each with a proposed default |
| Branch and PR split | Suggested branch name(s) and how to keep each PR at or below `size/M` |

## Cross-phase rules

- LLM calls go through the model tiers of DECISIONS §2 only, never a model name. Unit tests mock the LLM client; billable calls run only through explicit commands.
- Engine code under `apps/` contains no pack table, column, metric or industry name. From Phase 3 onward a repository check enforces this.
- From Phase 4 onward every phase reruns `eval.py --pack ecommerce_twin` and attaches the report to its PR; scores must not regress.
- Each LangGraph node is a pure function of its input state plus injected clients, unit-tested in isolation.
- Every service binds to loopback; credentials never reach the browser or an LLM prompt. From Phase 13 onward a secret a user enters is stored encrypted in the app state or in ClickHouse, never in a file the user edits.
- ClickHouse initialization scripts run only on a fresh volume; any schema change also ships an idempotent apply path for existing volumes. From Phase 13 onward that path is a numbered schema change applied by `jobs.migrate`. Volumes are never deleted to make a check pass.
- Phases 13 to 21 replace behaviour of Phases 0 to 12 one piece at a time ([DECISIONS §16](../DECISIONS.md#16-transition-from-v3)). A phase removes only what it replaces, and the application answers the acceptance question at the end of every phase.
- A measurement a plan asks for is recorded under `docs/eval/` or in the document the plan names, with the command that produced it; a decision that depends on it is written into DECISIONS in the same change.
- Each phase updates README.md (status and commands) and CHANGELOG.md.

## Phases

| Phase | Plan |
|---|---|
| 0 | [Repository foundation and infrastructure](phase-00-repository-and-infrastructure.md) |
| 1 | [Data and marts](phase-01-data-and-marts.md) |
| 2 | [Hand-written Domain Pack and compiler](phase-02-domain-pack-and-compiler.md) |
| 3 | [Core agent on the CLI](phase-03-core-agent-cli.md) |
| 4 | [Eval harness](phase-04-eval-harness.md) |
| 5 | [Logging and tracing](phase-05-logging-and-tracing.md) |
| 6 | [RBAC and auth](phase-06-rbac-and-auth.md) |
| 6B | [Web app on sample data](phase-06b-web-app-on-sample-data.md) |
| 7 | [API and streaming](phase-07-api-and-streaming.md) |
| 8 | [Conversation](phase-08-conversation.md) |
| 9 | [Chat and chart frontend](phase-09-chat-and-charts-frontend.md) |
| 9B | [Input screening](phase-09b-input-screening.md) |
| 9C | [Search on Qdrant](phase-09c-search-on-qdrant.md) |
| 9D | [Model routing](phase-09d-model-routing.md) |
| 9E | [Data sources](phase-09e-data-sources.md) |
| 10 | [Automated onboarding](phase-10-automated-onboarding.md) |
| 11 | [Industry neutrality proof](phase-11-industry-neutrality.md) |
| 12 | [Admin, audit and feedback loop](phase-12-admin-audit-feedback.md) |
| 13 | [App state and first-run setup](phase-13-app-state-and-setup.md) |
| 14 | [Model providers in the application](phase-14-model-providers.md) |
| 15 | [Individual and team sign-in](phase-15-sign-in-modes.md) |
| 16 | [One image, one container](phase-16-single-container-image.md) |
| 17 | [Connect data sources in the application](phase-17-data-source-connections.md) |
| 18 | [SQL Server sources](phase-18-sql-server-sources.md) |
| 19 | [Instant pack from a connected source](phase-19-instant-pack.md) |
| 20 | [Search in ClickHouse and optional documents](phase-20-search-in-clickhouse.md) |
| 21 | [Hardening and first release](phase-21-hardening-and-release.md) |
