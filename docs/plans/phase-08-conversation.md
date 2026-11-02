# Phase 8: Conversation

## Goal

Handle the full set of intents and follow-up questions: the router classifies each turn, `load_context` restores the previous turn from `chat_messages`, and the clarify, `metadata_qa`, `chart_edit` and `out_of_scope` branches answer without running unnecessary SQL.

## Scope

- `load_context` and `router` nodes (DECISIONS §6 steps 1-3).
- `clarify` in `gate`, using pack default conventions first.
- `metadata_qa` over glossary and `kb_docs`, `chart_edit` reusing the previous result, `out_of_scope` replies.
- Writing each turn to `chat_messages`, with a revision per turn so edits and retries replace later turns.
- Conversation management for the Chat app sidebar (DECISIONS §15): list, search, pin, rename, personal groups and delete.

## Out of scope

- The chart recommender rules and UI (Phase 9); `chart_edit` here produces a ChartSpec through a minimal recommender interface that Phase 9 fills.
- Company document ingestion (Phase 10); `metadata_qa` works with whatever `kb_docs` holds.

## Prerequisites

- Phases 5 and 7: `chat_messages` table, `/ask` with `conversation_id`.

## Deliverables

```text
apps/api/app/agent/nodes/load_context.py router.py clarify.py
                         metadata_qa.py chart_edit.py out_of_scope.py
apps/api/app/conversation/store.py       # read/write chat_messages, conversations, conversation_groups
apps/api/app/api/conversations.py        # list, search, read, update, delete conversations; groups
infra/clickhouse/                        # chat_messages columns turn, revision, result; conversations and
                                         # conversation_groups tables; fresh-volume init plus apply path
apps/api/prompts/router.v1.md metadata_qa.v1.md
```

## Tasks

1. **Conversation store (test first).** The api generates `conversation_id` (random UUIDv4) on a conversation's first turn and writes its `conversations` row with the first question cut to 80 characters as title; every later write and read checks that `(user_id, conversation_id)` belongs to the requesting user and returns 404 otherwise, with negative tests for a foreign id. Write user and assistant turns with their turn number, revision, QuerySpec and the shaped Result JSON (at most 5,000 rows) in `chat_messages.result`. The store writes synchronously, bypassing the async log writer, and the assistant turn is written before `done` is sent, so an immediate follow-up can read it; read the last N turns per conversation, scoped to the requesting user.
2. **load_context.** Business profile, last N turns of the current thread (the latest revision of each turn, without turns replaced by an edit or retry of an earlier turn), previous QuerySpec and result.
3. **router (test first with a fake LLM).** Structured output with one of four intents; low-confidence or invalid output falls back to `data_query` only if extraction succeeds, otherwise clarify.
4. **Follow-ups in extract.** Extract receives the previous QuerySpec and returns a delta (for example "shift periods by -1 year", "change dimension to category"); `resolve_time` applies period shifts deterministically. Test: "What about last year?" after the acceptance question shifts both periods one year back.
5. **clarify.** `gate` asks when a term maps to several metrics or columns with no pack convention, or a period is missing; the event carries options with stable ids, and choosing one is a follow-up turn.
6. **metadata_qa.** Answer definitions from glossary and `kb_docs` hits; the prompt forbids numbers from documents and states that retrieved text is data, not instructions.
7. **chart_edit.** Reuses the stored result and calls the recommender with the requested type; never calls `generate_sql` or `execute`. Test asserts no SQL node runs.
8. **out_of_scope.** Short fixed-style reply from the `fast` alias in the language of the question.
9. **Branch event sequences.** Extend DECISIONS §6 with: `metadata_qa`: `status* -> summary -> done`; `chart_edit`: `status* -> result -> chart_spec -> done`, re-sending the stored result so the client always has the rows it renders; `out_of_scope`: `status* -> summary -> done`. Tests assert each sequence.
10. **Eval.** Activate intent scoring and the ambiguous, out-of-scope, follow-up and chart-edit categories.
11. **Conversation endpoints (test first).** `GET /conversations` (the user's conversations with title, group, pinned and last activity, newest first, paginated), `GET /conversations/search?q=` (titles and the user's own questions, case- and diacritic-insensitive, in that user's conversations only), `GET /conversations/{id}` (the current thread), `PATCH /conversations/{id}` (title, pinned, group), `DELETE /conversations/{id}`, and `GET/POST/PATCH/DELETE /conversation-groups`. Every change writes a new `ReplacingMergeTree` row with the update time as version; reads use `FINAL` and skip deleted rows. Deleting a group moves its conversations back to no group. Negative tests: another user's conversation or group is 404 on every endpoint, and a deleted conversation is gone from list, search and reads.
12. **Edit and retry (test first).** `POST /ask` accepts an optional `edit_of_turn`: the question replaces that user turn under a new revision, and the answer follows it; a retry re-asks the stored question of the turn under a new revision. Turns after an edited or retried turn leave the thread and the context. Test: edit turn 1 of a three-turn conversation; the thread has one turn pair and `load_context` sees only the edited question.

## Contracts

- `chat_messages` row: `conversation_id, turn, revision, user_id, role, content, query_spec, result, trace_id, ts`; `result` holds the shaped Result JSON (at most 5,000 rows) of assistant turns. The current thread holds, for each turn, its latest revision, and stops before any turn whose latest revision is older than the latest revision of an earlier turn.
- `conversations` row: `user_id, conversation_id, title, pinned, group_id, deleted, created_at, updated_at`; `conversation_groups` row: `user_id, group_id, name, deleted, updated_at`. Both `ReplacingMergeTree(updated_at)` ordered by `(user_id, id)`, 90-day TTL on `updated_at`.
- `/ask` request gains `edit_of_turn: int | null` and `retry_of_turn: int | null` (at most one).
- `clarify` event: `{trace_id, question, options: [{id, label}]}`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

## Definition of done

| DoD item | Proof |
|---|---|
| "What about last year?" uses the previous QuerySpec | Test plus a two-turn curl transcript |
| "Draw it as a line" generates no SQL | Test asserting no SQL node ran; trace shows no `sql_runs` row |
| An ambiguous question returns clarify | Eval category `ambiguous` |
| Eval gains the corresponding groups | Report shows the new categories |
| A user lists, renames, pins, groups and deletes only their own conversations | Endpoint tests including foreign-id 404s |
| Editing an earlier question replaces the turns after it | Store and `load_context` test |

## Risks and open questions

1. **Where the previous result lives.** Settled: the shaped result is stored in `chat_messages.result` within the 90-day TTL (DECISIONS §10).
2. **Relative phrases in follow-ups.** "Last year" can mean relative to today or to the previous periods. Default: relative to the previous turn's periods when a previous QuerySpec exists.
3. **Context length.** Default: N = 6 turns; only QuerySpecs and summaries are sent to the LLM, never full result rows.
4. **Search cost.** Search scans the user's rows by the `(user_id, …)` key with `positionCaseInsensitiveUTF8` over folded text. Default: enough for the lab; a search index is out of scope.
5. **Existing `chat_messages` columns.** Phase 5 created the table without `turn`, `revision` and `result`. Default: the apply job adds them with `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, and initdb creates them on a fresh volume.

## Branch and PR split

- `feat/agent/route-intents-and-store-turns`: tasks 1-3, 8.
- `feat/agent/answer-follow-up-questions`: tasks 4-5, 10.
- `feat/agent/answer-metadata-and-chart-edits`: tasks 6-7, 9.
- `feat/api/manage-conversations`: tasks 11-12.
