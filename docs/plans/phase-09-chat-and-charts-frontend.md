# Phase 9: Chat and chart frontend

## Goal

Give end users the Chat app of the Fitcher web app design ([docs/design/web-app.md](../design/web-app.md), DECISIONS §15): OIDC login, a conversation sidebar, a streaming chat that shows each step, tables, SQL, warnings, clarify buttons and charts chosen by backend rules and rendered through a ChartSpec -> ECharts adapter, with client-side chart switching, exports, feedback, message actions, an English/Vietnamese interface and light and dark themes.

## Scope

- Backend `chart_recommender` node implementing DECISIONS §8.
- Frontend login, chat, result panels, chart adapter, type switcher, PNG/CSV export, like/dislike.
- `feedback` writes.
- The design's visual system and shared components, the Chat app shell (sidebar, search, title menu, account menu) over the Phase 8 conversation endpoints, message actions, skeletons, interface language and theme.

## Out of scope

- The workspace console (Phase 10 builds its shell; Phases 10 and 12 its sections).

## Prerequisites

- Phases 7-8: `/ask` SSE, generated TypeScript contracts, conversation support.

## Deliverables

```text
apps/api/app/agent/nodes/chart_recommender.py
apps/api/app/api/feedback.py                     # POST /feedback
apps/web/
  app/(chat)/page.tsx
  app/api/ask/route.ts                           # server-side proxy, see open question 1
  app/api/feedback/route.ts                      # server-side proxy for feedback
  lib/auth/                                      # OIDC session
  lib/sse/parseStream.ts
  components/chat/ components/result/DataTable.tsx SqlView.tsx Warnings.tsx
  components/chart/ChartView.tsx TypeSwitcher.tsx
  lib/chart/toEChartsOption.ts allowedTypes.ts export.ts
  app/styles/tokens.css                          # design tokens, light and dark
  components/ui/                                 # Button, TextField, Chip, Tabs, Menu, Dialog, Toast, Tooltip, Skeleton, ...
  components/brand/                              # Logo, Finch, Icon
  components/chat/ChatLayout.tsx SearchDialog.tsx ProgressSteps.tsx AnswerCard.tsx NoticeCard.tsx ...
  lib/i18n/en.json vi.json                       # interface strings only
  lib/steps.ts                                   # graph node -> ProgressSteps step
```

## Tasks

1. **chart_recommender (test first).** Table-driven tests for every row of DECISIONS §8: KPI, line with at most 6 series, bar with horizontal switch for long labels, grouped bar, pie only for share with at most 6 non-negative groups, scatter, table fallback. `allowed_types` lists every type valid for the data; time series never allow pie. The backend decides bar orientation and records it in an optional ChartSpec field `orientation: vertical | horizontal` (open question 4), so the frontend never duplicates the rule. The `fast` tie-break runs only when two rules match equally.
2. **Auth.** OIDC authorization code with PKCE against Keycloak; session held server-side; the api call carries the access token from the server.
3. **SSE chat.** Stream parser (tests for split frames, multiple events per chunk, heartbeats); per-node status list; cancel button aborts the request. Every request sends the browser's IANA time zone from `Intl.DateTimeFormat().resolvedOptions().timeZone`.
4. **Result panels.** TanStack Table with column formats from `Result.columns`; SQL view; warning banner; clarify options as buttons that send a follow-up turn.
5. **Chart adapter (test first).** `toEChartsOption(spec, result)` pure function; tests for each chart type, series grouping by `series`, sort and number format.
6. **Type switcher.** Changes only the local ChartSpec; types outside `allowed_types` are disabled with an explanation; no network request (asserted in a test).
7. **Export.** PNG through the ECharts instance, CSV from `Result` rows.
8. **Feedback.** Like/dislike with optional note -> the `app/api/feedback` server route forwards it with the session's access token and `trace_id` -> `POST /feedback`, which rejects a `trace_id` whose run belongs to another user -> `agent_logs.feedback`. A negative test covers a foreign `trace_id`.
9. **Visual system.** Tokens from the design as CSS variables for light and dark (system preference unless the user picks one, kept in local storage), Inter through `next/font` with the Vietnamese subset, Lucide icons, the brand `Logo` and `Finch` from `docs/brand`. Shared components follow the design's names; contrast checks for both themes run in a unit test over the token pairs.
10. **Chat shell.** `ChatLayout` with New chat, Search (`SearchDialog`, Ctrl K), Pinned, Groups and Recent (today, past week, past month), the per-conversation menu (pin, rename, move to and remove from group, delete with confirmation), group management, a resizable and collapsible sidebar that becomes a drawer below 768px, the title menu and the account menu (language, theme, console entry for console roles, sign out), all over the Phase 8 conversation endpoints through server routes.
11. **Answer anatomy and states.** `ProgressSteps` maps graph nodes to the design's steps (`lib/steps.ts`), shows the repair attempt, collapses into "How I got this"; `AnswerCard`, `ClarifyOptions`, `DefinitionAnswer` and `NoticeCard` (denied, out of scope, failed, empty, network, stopped); skeletons while a conversation opens and an answer streams. The type switcher labels `pie` as donut.
12. **Message actions.** Copy, like, dislike with note and retry under answers; copy and edit under the user's messages; edit and retry call `/ask` with `edit_of_turn` or `retry_of_turn` and replace the later turns in the view.
13. **Interface language.** An EN/VI switch over `lib/i18n` dictionaries, kept in local storage; number and date formats follow it. Content never changes language: every message, answer and pack text carries its own `lang` attribute. A test switches the language on a rendered answer and asserts the summary text is unchanged while labels change.

## Contracts

- `ChartSpec` from Phase 7; frontend imports only generated types.
- New web dependencies (pinned): `echarts`, `echarts-for-react`, `@tanstack/react-table`, an OIDC client library, `lucide-react`, a unit test runner. No component library: the design's components are built in `apps/web`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web ci
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
```

Plus a manual browser check of the acceptance question, recorded with screenshots in the PR.

## Definition of done

| DoD item | Proof |
|---|---|
| Acceptance question shows a grouped bar | Recommender test and screenshot |
| Switching bar / table / line makes no API call | Component test with a network spy |
| Never a pie for a time series | Recommender test and disabled pie in the switcher |
| Switching EN/VI changes the interface, not the answer | Component test |
| Every chat screen works at 1440, 768 and 390px in light and dark | Screenshots in the PR |

## Risks and open questions

1. **Token handling.** Default: a Next.js server route proxies `/ask` so access tokens stay out of browser JavaScript; the browser holds only an httpOnly session cookie.
2. **OIDC library.** Default: Auth.js with the Keycloak provider; alternative: a smaller OIDC client. Decide by compatibility with the pinned Next.js version.
3. **Frontend test runner.** Default: Vitest with Testing Library; end-to-end browser tests are optional for this lab.
4. **Bar orientation in ChartSpec.** DECISIONS §7 has no orientation field. Default: add optional `orientation` to the ChartSpec contract in DECISIONS §7, with the owner's approval, in this phase's first PR, which also updates the Pydantic `ChartSpec` model and regenerates the TypeScript types with the Phase 7 generator.

## Branch and PR split

- `feat/agent/recommend-chart-types`: task 1.
- `feat/web/sign-in-and-stream-chat`: tasks 2-4.
- `feat/web/render-and-switch-charts`: tasks 5-7.
- `feat/web/record-answer-feedback`: task 8.
- `feat/web/build-design-system`: task 9, before tasks 2-8 use the components.
- `feat/web/manage-conversations-in-the-sidebar`: tasks 10 and 12.
- `feat/web/translate-the-interface`: tasks 11 and 13.
