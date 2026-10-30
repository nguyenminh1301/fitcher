# Phase 8: Conversation

## Goal

Handle the full set of intents and follow-up questions: the router classifies each turn, `load_context` restores the previous turn from `chat_messages`, and the clarify, `metadata_qa`, `chart_edit` and `out_of_scope` branches answer without running unnecessary SQL.

## Scope

- `load_context` and `router` nodes (DECISIONS §6 steps 1-3).
- `clarify` in `gate`, using pack default conventions first.
- `metadata_qa` over glossary and `kb_docs`, `chart_edit` reusing the previous result, `out_of_scope` replies.
- Writing each turn to `chat_messages`.

## Out of scope

- The chart recommender rules and UI (Phase 9); `chart_edit` here produces a ChartSpec through a minimal recommender interface that Phase 9 fills.
- Company document ingestion (Phase 10); `metadata_qa` works with whatever `kb_docs` holds.

## Prerequisites

- Phases 5 and 7: `chat_messages` table, `/ask` with `conversation_id`.

## Deliverables

```text
apps/api/app/agent/nodes/load_context.py router.py clarify.py
                         metadata_qa.py chart_edit.py out_of_scope.py
apps/api/app/conversation/store.py       # read/write chat_messages
apps/api/prompts/router.v1.md metadata_qa.v1.md
```

## Tasks

1. **Conversation store (test first).** Write user and assistant turns with QuerySpec and a reference to the shaped result; read the last N turns per conversation, scoped to the requesting user.
2. **load_context.** Business profile, last N turns, previous QuerySpec and result.
3. **router (test first with a fake LLM).** Structured output with one of four intents; low-confidence or invalid output falls back to `data_query` only if extraction succeeds, otherwise clarify.
4. **Follow-ups in extract.** Extract receives the previous QuerySpec and returns a delta (for example "shift periods by -1 year", "change dimension to category"); `resolve_time` applies period shifts deterministically. Test: "What about last year?" after the acceptance question shifts both periods one year back.
5. **clarify.** `gate` asks when a term maps to several metrics or columns with no pack convention, or a period is missing; the event carries options with stable ids, and choosing one is a follow-up turn.
6. **metadata_qa.** Answer definitions from glossary and `kb_docs` hits; the prompt forbids numbers from documents and states that retrieved text is data, not instructions.
7. **chart_edit.** Reuses the stored result and calls the recommender with the requested type; never calls `generate_sql` or `execute`. Test asserts no SQL node runs.
8. **out_of_scope.** Short fixed-style reply from the `fast` alias with the pack's language.
9. **Eval.** Activate intent scoring and the ambiguous, out-of-scope, follow-up and chart-edit categories.

## Contracts

- `chat_messages` row: `conversation_id, turn, user_id, role, content, query_spec, result, ts`; `result` holds the shaped Result JSON (at most 5,000 rows) of assistant turns.
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

## Risks and open questions

1. **Where the previous result lives.** `chart_edit` needs rows without re-running SQL. Default: the shaped result is stored in `chat_messages.result` (see Contracts) within the 90-day TTL. DECISIONS §10 lists the QuerySpec but not the result for this table, so the owner confirms the addition.
2. **Relative phrases in follow-ups.** "Last year" can mean relative to today or to the previous periods. Default: relative to the previous turn's periods when a previous QuerySpec exists.
3. **Context length.** Default: N = 6 turns; only QuerySpecs and summaries are sent to the LLM, never full result rows.

## Branch and PR split

- `feat/agent/route-intents-and-store-turns`: tasks 1-3, 8.
- `feat/agent/answer-follow-up-questions`: tasks 4-5, 9.
- `feat/agent/answer-metadata-and-chart-edits`: tasks 6-7.
