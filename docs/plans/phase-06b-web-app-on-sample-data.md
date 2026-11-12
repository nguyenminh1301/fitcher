# Phase 6B: Web app on sample data

## Goal

Build every screen of the Fitcher web app design ([design/web-app.md](../design/web-app.md), DECISIONS §15) before the api phases, so the product can be used and shown early. Every feature works: either through the real api or, until its backend phase lands, as a small realistic sample read from the active pack's `sample_data/` and marked with a Sample data badge. Phases 7-12 then wire one feature at a time, each following its plan's "Web wiring" section.

## Scope

- Visual system, light and dark themes, the English/Vietnamese interface switch.
- Chat app: sidebar with conversations, search and groups; answers with progress steps, summary, warnings, chart, table, SQL, notices, clarify options and message actions; chart type switching and export.
- Workspace console: role-based navigation and every section (Review, Documents, Datasets, Feedback, Evaluation, Runs and trace, Audit, Costs, Users).
- A typed api client with a `mock` and an `http` implementation per feature, and a per-feature source switch.
- Generated TypeScript types for the backend contracts that already exist (QuerySpec, Result); this moves Phase 7 task 7 forward.
- Pack-owned sample data with its JSON Schemas, and the pack isolation check extended to `apps/web`.

## Out of scope

- Every backend endpoint, SSE against a real stream and Keycloak sign-in (Phase 7).
- Conversation storage on the server (Phase 8), chart recommendation and feedback storage (Phase 9), onboarding and admin backends (Phases 10 and 12).

## Prerequisites

- Phase 6 merged: the pack's policy roles are final, and the demo identities use them.
- The design artifact and the brand files in `docs/brand`.

## Deliverables

```text
apps/web/
  app/styles/tokens.css                  # design tokens, light and dark
  app/(chat)/                            # Chat app routes
  app/(console)/console/                 # console routes, one folder per section
  app/api/sample/[file]/route.ts         # serves the active pack's sample data files
  components/ui/ components/brand/ components/chat/ components/console/
  lib/i18n/ lib/theme.ts lib/storage.ts lib/steps.ts lib/chart/ lib/chat/ lib/console/
  lib/contracts/                         # generated from the Pydantic contracts
  lib/api/client.ts sources.ts provisional.ts mock/ http/ index.ts
  tests/                                 # Vitest
packs/_schema/sample_scenarios.schema.json sample_console.schema.json
packs/ecommerce_twin/sample_data/scenarios.json console.json
scripts/generate_contract_types.py
scripts/check_pack_isolation.py          # extended to apps/web
compose.yaml                             # web mounts packs read-only, gets ACTIVE_PACK
```

## Tasks

1. **Visual system (test first).** Tokens from the design (brand neutrals Ink `#111111`, Paper `#FFFFFF`, Mist `#E8E8EA`, Graphite `#6B6B70`, Primer status, accent, data and syntax colours, 4px spacing, radii 3, 6, 12, 24 and pill) for light and dark; Inter with the Vietnamese subset; brand and shared components named as in the design; theme and language kept per browser through storage helpers that never throw. Tests: WCAG AA contrast of every text token pair in both themes, identical keys in the English and Vietnamese dictionaries, fallback of missing keys, storage helpers with a throwing `localStorage`. CI's web job runs `npm run test`.
2. **Generated contract types (test first).** `scripts/generate_contract_types.py` writes the JSON Schemas of QuerySpec and Result into `apps/web/lib/contracts/schemas/`; `npm run contracts:generate` turns them into TypeScript. A Python test fails when a committed schema differs from its model, and a web test fails when a committed type differs from its schema.
3. **Sample data (test first).** Two files per pack, validated by their schemas: `scenarios.json` (suggested questions and about eight answer scenarios: top N, two-period comparison, monthly trend, single figure, clarify, a role-limited answer, one SQL repair then success, failure) and `console.json` (demo identities with the pack's roles plus `pack_reviewer` and `admin`, sample conversations and every console section). Sample data is hand-written with plausible numbers and never copied or derived from a licensed dataset. A server route serves only these two files of `ACTIVE_PACK`; a missing folder is a 404 that every mock surface shows as an explained empty state.
4. **Api client.** `FitcherApi` grouped by feature (`auth`, `chat`, `conversations`, `feedback`, `datasets`, `review`, `documents`, `feedbackReview`, `evaluation`, `runs`, `audit`, `costs`, `users`); `sources.ts` maps each feature to `mock` or `http` (all `mock` in this phase); `http` methods throw "not wired" until their phase. Types without a Pydantic model yet (ChartSpec, ask events, conversations, console rows) live only in `provisional.ts` and are deleted there by the phase that adds their model. `SampleDataBadge` shows on every surface whose feature is `mock`.
5. **Mock chat and conversations (test first).** The mock matches a question to a scenario and streams the event sequences of DECISIONS §6 (`status*`, then `sql`, `result`, `chart_spec`, `summary`, `done`; or `clarify`/`deny`/`error`) with realistic delays; a role outside the scenario's roles gets `deny`; Stop aborts with a "stopped" notice; an unmatched question gets a sample-only notice with example questions. Conversations, pins, groups, renames and deletes persist in browser storage per demo identity, falling back to memory. `lib/steps.ts` maps graph nodes to the design's nine steps.
6. **Chat shell.** `ChatLayout` per the design: New chat, Search (Ctrl K), Pinned, Groups, Recent (today, past week, past month), conversation and group menus, resizable and collapsible sidebar that becomes a drawer below 768px, title menu, account menu with language, theme, console entry for console roles and the demo identity picker (shown only while `auth` is `mock`), empty state with suggestions, `SignInScreen` with the Keycloak action disabled until Phase 7.
7. **Answers and actions.** `ProgressSteps` (live, repair attempts, Stop, collapses into "How I got this"), `AnswerCard`, `WarningBanner`, `NoticeCard` kinds, `ClarifyOptions`, `DefinitionAnswer`, `MessageBubble` copy and edit, `FeedbackBar` copy, like, dislike with note and retry. Content blocks keep their `lang` when the interface language changes.
8. **Charts, table and SQL (test first).** `toEChartsOption(spec, result, palette, locale)` per chart type (bar vertical and horizontal, grouped bar, line, pie shown as donut, scatter, KPI, table); local type switching with no request; disabled types with their reason; PNG and CSV export; `DataTable` with 20 rows per page and cards below 640px; `SqlView` read-only with copy.
9. **Console shell (test first for the navigation rule).** `ConsoleLayout`, grouped navigation showing only the sections the identity's roles allow (DECISIONS §15), list pages of 20 rows that become cards below 640px, detail pages with back button, header actions and two panes stacked below 900px.
10. **Console sections.** Datasets, Review (filters, detail, edit, approve, delete, Test run, Proposals tab), Documents (upload rules, statuses, delete, paid-AI draft action), Feedback, Evaluation (per-layer rates against the 80% threshold, paid-AI run with confirmation), Runs and trace (`TraceTimeline`), Audit, Costs (labelled as an estimate), Users (role changes, disable and enable; never on the acting identity).
11. **Acceptance.** Walk every screen in both languages and themes at 1280px and 375px; README explains how to run the web app on sample data.

## Contracts

- `apps/web/lib/api/client.ts`: the `FitcherApi` interface; every later phase implements a feature of it in `lib/api/http/`.
- `apps/web/lib/api/sources.ts`: `sources[feature]` is `mock` or `http`; wiring a feature means switching it to `http`.
- `GET /api/sample/{scenarios|console}` (web server route): the active pack's sample files, 404 when missing.
- `packs/<pack>/sample_data/` validated by `packs/_schema/sample_scenarios.schema.json` and `sample_console.schema.json`.

## Verification

```bash
npm --prefix apps/web ci
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
uv run --project apps/api pytest -c apps/api/pyproject.toml
python scripts/check_pack_isolation.py
docker compose config --quiet
docker compose up --build --wait web
```

## Definition of done

| DoD item | Proof |
|---|---|
| Every screen of the design opens and works on sample data | Screenshot set in the PRs |
| English and Vietnamese, light and dark everywhere; usable at 375px | Screenshots and the language test |
| Every mock feature shows the Sample data badge | Badge test |
| No pack names in `apps/web` | `check_pack_isolation.py` |
| Web unit tests, typecheck and build pass in CI | CI run |

## Risks and open questions

1. **Sample data drifting from the real contracts.** Default: one provisional type file replaced by generated types as each backend lands; schema tests on the sample files.
2. **A demo mistaken for real answers.** Default: the badge on every mock surface and the sample-only notice for unmatched questions.
3. **Size.** Default: five PRs, the chat path before the console.

## Branch and PR split

- `feat/web/add-visual-system`: task 1.
- `feat/web/add-api-client-with-sample-data`: tasks 2-5.
- `feat/web/build-chat-shell`: task 6.
- `feat/web/show-answers-and-charts`: tasks 7-8.
- `feat/web/build-console-on-sample-data`: tasks 9-10, split in two if it exceeds 1000 lines.
- Task 11 rides with a final docs PR.
