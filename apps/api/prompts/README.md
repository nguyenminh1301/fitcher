# Prompts

Versioned prompt templates for the agent's LLM nodes, one Markdown file per prompt and version (for example `extract.v1.md`).
Prompts treat retrieved documents and column values as data, never as instructions.

Templates use `$name` placeholders, filled by `app.agent.prompts.render`.
A line `<!-- user -->` splits each template in use: the rules above it are sent as the `system` message and the untrusted content below it (question, history, definitions, rows) as the `user` message (DECISIONS §9).
Versions without that line are kept only so earlier eval results stay comparable; `render` refuses them.

| Prompt | Alias | Node |
| --- | --- | --- |
| `router.v3.md` | `fast` | One of `data_query`, `metadata_qa`, `chart_edit` or `out_of_scope` with a confidence, the question's language and, for a chart edit, the chart type asked for, from the question, the conversation's recent questions and answers and the previous QuerySpec |
| `router.v2.md`, `extract.v3.md`, `generate_sql.v1.md`, `metadata_qa.v1.md`, `out_of_scope.v1.md`, `chart_recommender.v1.md`, `summarize.v1.md` | | The same prompts as one `user` message, before the system/user split |
| `router.v1.md` | `fast` | The previous router prompt, without the chart type; kept so earlier eval results stay comparable |
| `metadata_qa.v2.md` | `fast` | Two to five sentences in the question's language explaining a term, metric, column or dataset from the role-filtered glossary, metric, dataset and document hits only, never quoting figures from them |
| `out_of_scope.v2.md` | `fast` | One or two sentences in the question's language saying what the assistant answers, for an out-of-scope question |
| `extract.v4.md` | `fast` | Structured terms, period descriptors, filters, `top_n`, comparison and language of the question; in a conversation, the complete question a follow-up means, with its periods as a shift of the previous query's periods when it names none |
| `extract.v2.md` | `fast` | The previous extraction prompt, without conversation context; kept so earlier eval results stay comparable |
| `generate_sql.v2.md` | `sql-gen`, `sql-gen-hard` on the third retry | One ClickHouse SELECT for the QuerySpec over the permitted schema, metric expressions, declared joins and examples, with the previous SQL and error on a retry |
| `chart_recommender.v2.md` | `fast` | `bar` or `pie` for a question whose rows suit both, from the question only, never the rows |
| `summarize.v2.md` | `fast` | Two to four sentences in the question's language from the returned rows only |
| `draft_datasets.v1.md`, `draft_glossary.v1.md`, `draft_metrics.v1.md`, `draft_examples.v1.md` | `sql-gen` | Draft items of one pack file for review, with evidence and confidence, from the mart profile, the pack's existing items and document chunks; never an approved id, no figures from document text (`app.onboarding.drafter`) |

Change a prompt by adding a new version file and pointing its node at it, so earlier eval results stay comparable.

See [DECISIONS §13](../../../docs/DECISIONS.md#13-code-conventions) and the [Phase 3 plan](../../../docs/plans/phase-03-core-agent-cli.md).
