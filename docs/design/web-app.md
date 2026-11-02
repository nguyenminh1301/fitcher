# Fitcher web app design

This is the interface specification behind [DECISIONS §15](../DECISIONS.md#15-web-application). It summarizes the Fitcher web app design: the screens, their features and states, and the component names that `apps/web` uses, so a design element maps to one component in code. Behaviour and data rules stay in DECISIONS; where this page and DECISIONS disagree, DECISIONS wins.

The design makes one promise visible everywhere: every number comes from a query the user can open. The chrome is domain-neutral ("data", "result", "query", "pack item"); industry words appear only in pack content and results.

## Surfaces

| | Chat app | Workspace console |
|---|---|---|
| Who | every role | `pack_reviewer`, `admin` |
| Layout | history sidebar and a centred 768px conversation column (`ChatLayout`) | top bar with the pack, grouped navigation and pages in a panel up to 1160px (`ConsoleLayout`) |
| Density | 16/24 message text, 12px box corners | 14/20 text, 6px box corners, 28px toolbar buttons |
| Below 768px | the sidebar becomes a drawer | the navigation becomes a drawer, panes stack, tables become cards |

`SignInScreen` comes first: one "Sign in with company account" action (Keycloak), the active pack and a short trust statement.

## Chat app

### Sidebar and conversations

- Order: New chat, Search, then Pinned, Groups, Recent (Today, Past week, Past month), and the account menu at the bottom.
- Each conversation has a menu: Pin, Rename, Move to group, Remove from group, Delete (with a confirmation dialog). Groups can be created, renamed and deleted; deleting a group returns its conversations to Recent.
- Search opens `SearchDialog` (also Ctrl K): filters as the user types, arrow keys and Enter open a result; full screen on phones.
- The sidebar can be resized from 220 to 440px (drag, arrow keys on the handle, double-click resets) and collapsed on desktop.
- The top bar shows the conversation title and its group; it opens the same menu. The active pack is a small label inside the composer.
- The account menu holds the language and theme switches, the console entry for console roles, and sign out.

### Empty state

The question title, the `Composer` with the trust line and four to six suggested questions as chips, at least one in the other language.

### Anatomy of an answer

An assistant turn shows the `Finch` mascot and, in order:

1. `ProgressSteps`: a live list of steps (understanding the question, resolving dates, finding data, building the query, writing SQL, checking SQL safety, running the query, choosing a chart, writing the summary), with "Repairing SQL (attempt n of 3)" when a query is retried and a Stop button. When the answer completes it collapses into a "How I got this" toggle. Each step maps to one or more graph nodes.
2. The summary: two to four sentences in the question's language, restating figures from the result only.
3. `WarningBanner` for each warning (partial coverage, empty result, truncated rows).
4. `ChartCard`: `ChartView` plus `TypeSwitcher` with grouped bar, bar (vertical or horizontal), line, donut (the contract's `pie`), scatter, KPI and table. Types outside `allowed_types` stay visible and disabled with the reason as a tooltip. Switching is local. PNG export.
5. `DataTable`: sortable columns formatted by type and format, CSV export, 20 rows per page, a "showing first N rows" notice when truncated; rows become cards below 640px.
6. `SqlView`: collapsible, highlighted, read-only, with copy and a "Read-only, checked against your access" label.
7. `FeedbackBar`: copy, like, dislike (opens an optional note) and retry.

The user's own `MessageBubble` offers copy and edit; editing replaces that question and every answer after it, then answers again.

### Other answers and states

- `ClarifyOptions`: the question and two to four option buttons; picking one sends a follow-up turn.
- `NoticeCard` kinds: denied (names what was blocked, says nothing was queried and who can help; neutral, never red), out of scope (with example questions), failed after three attempts (last SQL and database error, no guessed result), empty result, network or stream error, stopped.
- `DefinitionAnswer`: glossary or document text with numbered source citations, no SQL.
- Chart edit follow-ups ("show that as a line chart") update the last chart without a new query.
- `Skeleton` while a past conversation opens and while an answer streams.

## Workspace console

| Group | Section | Role | Content |
|---|---|---|---|
| Knowledge | Review | `pack_reviewer` | Pack items by file with draft/approved filters; `ReviewItem` detail with evidence (flagged when it cites a deleted document), `ConfidenceMeter`, inline edit, approve, delete and Test run for metrics; a Proposals tab for examples proposed from feedback, approved only after masked values are replaced and the SQL is test-run |
| Knowledge | Documents | `pack_reviewer` | `UploadDropzone` (PDF, DOCX, MD, TXT, XLSX, 20 MB), `DocumentRow` with role chips, status (processing, indexed, failed with error), delete with confirmation, and "Draft pack items" marked as using paid AI; duplicate and compiling states |
| Knowledge | Datasets | `pack_reviewer` | Read-only datasets of the compiled pack: columns, types, roles, readable roles |
| Knowledge | Feedback | `pack_reviewer` | Likes and dislikes with question, note and trace; "Propose example" sends one run to Proposals |
| Quality | Evaluation | `pack_reviewer`, `admin` | Per-layer rates, the 80% threshold, required categories, failed cases; `admin` can run the eval set (paid AI, confirmation) |
| Observe | Runs and trace | `admin` | Paginated runs filtered by user, dates and status; `TraceTimeline` with step durations, LLM calls (alias, tokens, estimated cost), SQL attempts with errors and the access decision |
| Observe | Audit | `admin` | Allow and deny decisions with role, blocked tables and time |
| Observe | Costs | `admin` | Estimated LLM cost by day, alias and model in the chat's chart card style |
| Administration | Users | `admin` | Users with their pack roles and status; change roles, disable and enable; a role overview |

Lists open into detail pages with a back button, a header of actions and two panes (stacked below 900px). Each section and detail page shows a page skeleton while it loads.

## Language and content

- The EN/VI switch translates the interface: navigation, buttons, labels, page titles, step labels, notices the app raises, chart axes and legends, number and date formats.
- It never translates what was said: user messages, the assistant's replies (summary, warnings, clarify options, notices, definitions and citations), pack content, data values and column names. Every content block carries its `lang` attribute.
- Vietnamese strings run about 30% longer: buttons size to content and labels wrap; only history titles and file names truncate, with the full text in a tooltip.
- Voice: plain, calm and specific, first person for the assistant, sentence case everywhere, no exclamation marks. Never show credentials, tokens, keys, connection strings or host names; model calls are named by alias.

## Visual foundations

- Colour: the brand neutrals (Ink `#111111`, Paper `#FFFFFF`, Mist `#E8E8EA`, Graphite `#6B6B70`) with Primer status, accent, data and syntax colours; the primary button is Ink on Paper, inverted in dark mode. Status always carries an icon and a word.
- Data colours: the current period or main measure in blue, the comparison period in grey with a hatch, then orange, green, purple and pink; lines differ by dash and marker as well as colour.
- Type: Inter with the Vietnamese subset and Primer's scale; monospace for SQL and identifiers.
- Space and shape: a 4px scale; radii 3, 6, 12 and 24px plus pills; depth by borders first, with light shadows for the composer, menus, toasts and dialogs.
- Motion: 120ms colour transitions, a 200ms drawer, a spinner on the active step, the finch bobbing while an answer streams; all respect `prefers-reduced-motion`.
- Accessibility: WCAG 2.2 AA in both themes; a 2px focus ring; keyboard access to tabs, the chart switcher, clarify options, menus and dialogs (focus trapped and returned); live regions for streaming steps and new turns; charts are images with a description and the data table as their accessible equivalent.

## Component map

- Brand: `Logo`, `Finch`, `Icon`.
- Chat: `ChatLayout`, `ChatThread`, `MessageBubble`, `ProgressSteps`, `AnswerCard`, `WarningBanner`, `ChartCard`, `ChartView`, `TypeSwitcher`, `DataTable`, `SqlView`, `FeedbackBar`, `ClarifyOptions`, `DefinitionAnswer`, `NoticeCard`, `Composer`, `SearchDialog`, `SignInScreen`.
- Console: `ConsoleLayout`, `ReviewItem`, `ConfidenceMeter`, `UploadDropzone`, `DocumentRow`, `TraceTimeline`.
- Shared: `Button`, `TextField`, `Checkbox`, `Chip`, `Tabs`, `Segmented`, `StatusPill`, `Toast`, `Tooltip`, `Dialog`, `Menu`, `Skeleton`, `EmptyState`.
