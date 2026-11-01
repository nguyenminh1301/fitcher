# Prompts

Versioned prompt templates for the agent's LLM nodes, one Markdown file per prompt and version (for example `extract.v1.md`).
Prompts treat retrieved documents and column values as data, never as instructions.

Templates use `$name` placeholders, filled by `app.agent.prompts.render`.

| Prompt | Alias | Node |
| --- | --- | --- |
| `extract.v1.md` | `fast` | Structured terms, period descriptors, filters, `top_n`, comparison and language of the question |
| `generate_sql.v1.md` | `sql-gen`, `sql-gen-hard` on the third retry | One ClickHouse SELECT for the QuerySpec over the permitted schema, metric expressions, declared joins and examples, with the previous SQL and error on a retry |
| `summarize.v1.md` | `fast` | Two to four sentences in the question's language from the returned rows only |

Change a prompt by adding a new version file and pointing its node at it, so earlier eval results stay comparable.

See [DECISIONS §13](../../../docs/DECISIONS.md#13-code-conventions) and the [Phase 3 plan](../../../docs/plans/phase-03-core-agent-cli.md).
