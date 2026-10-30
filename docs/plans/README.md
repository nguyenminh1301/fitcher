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

- LLM calls go through LiteLLM aliases (`fast`, `sql-gen`, `sql-gen-hard`, `embed`) only. Unit tests mock the LLM client; billable calls run only through explicit commands.
- Engine code under `apps/` contains no pack table, column, metric or industry name. From Phase 3 onward a repository check enforces this.
- From Phase 4 onward every phase reruns `eval.py --pack ecommerce_twin` and attaches the report to its PR; scores must not regress.
- Each LangGraph node is a pure function of its input state plus injected clients, unit-tested in isolation.
- Every service binds to loopback in Compose; credentials stay in `.env` and never reach the browser or an LLM prompt.
- ClickHouse initialization scripts run only on a fresh volume; any schema change also ships an idempotent apply path for existing volumes. Volumes are never deleted to make a check pass.
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
| 7 | [API and streaming](phase-07-api-and-streaming.md) |
| 8 | [Conversation](phase-08-conversation.md) |
| 9 | [Chat and chart frontend](phase-09-chat-and-charts-frontend.md) |
| 10 | [Automated onboarding](phase-10-automated-onboarding.md) |
| 11 | [Industry neutrality proof](phase-11-industry-neutrality.md) |
| 12 | [Admin, audit and feedback loop](phase-12-admin-audit-feedback.md) |
