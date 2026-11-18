<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/banner/fitcher-banner-dark.png">
  <img alt="Fitcher: ask your data in plain language, get SQL, tables and charts back" src="docs/brand/banner/fitcher-banner-light.png" width="100%">
</picture>

Fitcher answers questions about a company's data. You ask in English or Vietnamese, for example "Top 10 best-selling products in Q1 2024 compared with Q1 2025", and it replies with the SQL it ran, a table, a chart and a short summary.

Everything fitcher knows about a company comes from its Domain Pack: a set of reviewed files describing the company's tables, business terms, metrics and who may see what. Swap the pack and the same app answers questions for a different business.

## What you can do with it

![Asking a question in plain language, reading the answer and chart, changing the chart, and exporting the chart as PNG and the data as CSV](docs/media/fitcher-demo.gif)

| Feature | What it means for a user |
| --- | --- |
| Ask about data | Ask for rankings, trends, comparisons between periods and filtered totals. Relative periods such as "last quarter" use the company's fiscal calendar and your time zone. |
| Hold a conversation | Ask a follow-up and it reuses the previous query. Ask to see the answer as a line chart and it redraws without querying again. Ask what a term means and it answers from the glossary and company documents. |
| Get asked back | When a question is unclear, fitcher asks which meaning you intended and offers the options. |
| Read only what you approved | A pack lists the tables and columns you approved. A question about other data is refused before any SQL is written, and the database user the agent runs as can read only the pack's marts. |
| Stay safe | Every question is screened for prompt injection before it reaches an AI model. For now the screener records its verdict and lets the question through; blocking is switched on once it is accurate enough in both languages. |
| Check the work | Each answer shows the SQL it ran and the steps it took, and the console opens the full trace of any run. |
| Add a new company | fitcher profiles the company's tables, reads its documents and drafts a pack. Drafted items answer at once, marked unreviewed until you approve them. |
| Measure quality | Each pack has a set of test questions with known answers, and the console shows whether at least 80% of them return the right result with the chosen models. |

The web app has a chat and a workspace console, in English and Vietnamese, light and dark themes, on desktop and phone.

## How it works

![How the pieces fit together](docs/architecture/system.svg)

The user talks to the web app, which streams answers from the API. fitcher is a personal app: there are no accounts, and the API answers only the machine it runs on unless an owner password is set and the browser signs in with it. The API runs the agent: it looks up the company's terms in the search index, sends language tasks to the AI models connected in the app, and runs SQL in ClickHouse as a read-only role. Models are called by task (fast replies, simple SQL, harder SQL), any task can use any model of a connected provider, and the pack's test results are shown next to each model. Search uses the provider's embedding model, or a local one when the provider has none. All of these services run together in one Docker image on one machine.

![How a question is answered](docs/architecture/question-flow.svg)

A question goes through a safety check first. The agent then works out what is being asked, matches the words to the company's metrics, checks that the question is clear and permitted, writes one read-only query, validates and runs it, and picks a chart. If the query fails, the agent fixes it and tries again up to three times; if it still fails, you see the last SQL and the error. Each step shows on screen as it happens, and the numbers in the answer always come from the database, never from the AI model.

The recording below shows one question in the app going through these steps, each lit on the diagram as it runs, with the graph nodes it passed. It then opens the SQL the answer ran, and a follow-up chart change takes the quick-reply path without querying again.

![A question in the app going through the steps of the diagram, then its SQL and a chart change](docs/media/fitcher-question-flow.gif)

![What the agent can read](docs/architecture/access-control.svg)

A pack reads only the datasets you approved. Publishing the pack gives its marts to one read-only database user, which is the user every query runs as, so the database itself stops a query from reading anything else. A question about other data is refused before any SQL is written, and every query and refusal goes to the audit log. The pack's search only keeps the AI's context small and relevant; the database user's grants are what enforce it.

| Component | Technology |
| --- | --- |
| Web app | Next.js, ECharts, TanStack Table |
| API and agent | FastAPI with streamed responses, LangGraph, sqlglot |
| AI models | OpenAI, Anthropic, Gemini, a local Ollama model or any OpenAI-compatible endpoint, called in process through the LiteLLM SDK; the provider's embedding model, or a local multilingual one with fastembed |
| Data and run logs | ClickHouse |
| Search index | ClickHouse, combining meaning-based and keyword search |
| Data modelling | dbt |
| Domain Packs | YAML checked against JSON Schema |

## Status

fitcher 0.0.1 is the first release of the one-image product: one `docker run`, setup in the browser, data sources and a first pack built in the application, backup and restore, and the security review of [docs/security.md](docs/security.md). The [decisions](docs/DECISIONS.md) and the [master plan](docs/MASTER_PLAN.md) record how it got here.

## Quick start

You need Docker. Start fitcher with one command:

```bash
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-data:/data ghcr.io/nguyenminh1301/fitcher
```

Open [localhost:3000](http://localhost:3000) and follow the setup: connect a model provider and its key, or a model server on this computer reached as `host.docker.internal` (on Linux add `--add-host=host.docker.internal:host-gateway` to the command). Everything is kept in the `fitcher-data` volume.

[docs/install.md](docs/install.md) covers the first start and the settings, [docs/operations.md](docs/operations.md) backup, restore, upgrades, limits and the load measurement, and [docs/security.md](docs/security.md) the threat model and hardening checklist. The install guide also covers jobs, local models and measured memory use.

A demo of the web app on sample data, with no backend, starts with `docker run -p 127.0.0.1:3000:3000 ghcr.io/nguyenminh1301/fitcher-demo` once the Demo workflow has published it from `main`.

To work on fitcher itself with the development datasets, the sample packs and separate services, follow the [development setup](CONTRIBUTING.md#development-setup).

## Using the API

These examples use the [development setup](CONTRIBUTING.md#development-setup), which publishes the API on port 8000. The API streams each answer as server-sent events. A request from the local machine needs no sign-in; a request that changes something must name the page it comes from in `Origin`, which the example sends:

```bash
curl -N -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:8000" -d '{"question":"Top 10 best-selling products in Q1 2024 compared with Q1 2025","timezone":"Asia/Ho_Chi_Minh"}' http://127.0.0.1:8000/ask
```

The stream reports each step as it starts and finishes, then sends the SQL, the result, the chart and the summary. A question that cannot be answered ends with a clarifying question, a refusal, a blocked notice or an error instead. The response names the conversation it started; send that id with the next question to ask a follow-up. Closing the connection stops the run and its database query.

The owner may ask 10 questions a minute by default. The same API manages conversations (list, search, rename, pin, group and delete), records likes and dislikes, and serves the console's admin pages. The [API docs](http://localhost:8000/docs) of a running stack list every endpoint.

## Bringing in a new company

![Bringing in a new company](docs/architecture/onboarding.svg)

A new company needs its own Domain Pack and nothing else. The Iowa Liquor Sales pack was built this way from a PostgreSQL database.

1. Connect the company's PostgreSQL, MySQL or SQL Server database (SQL Server is copied, never read live), or upload a CSV, Excel or Parquet file, on the console's Sources page or in the setup's Data step: enter the connection, test it, choose the tables and whether to read each live or copy it on a schedule (the [Sources section of the jobs guide](jobs/README.md#connecting-a-source-in-the-interface) gives the read-only user to create). Only ClickHouse holds the credentials. MongoDB and S3 sources are declared in a manifest.
2. Profile the tables to find their columns, date ranges and common values.
3. Upload manuals, policies and glossaries on the console's Documents page.
4. Let the AI draft the pack's terms, metrics and example questions, each with the evidence it used.
5. Review every draft in the console: edit it, test-run it and approve it.
6. Publish the pack and run its test questions.

Later, disliked or failed answers become example proposals. A reviewer corrects and approves them, and the next publish uses them. [packs/](packs/README.md#onboarding-a-company) covers the pack files and each step, and [jobs/](jobs/README.md) lists the commands.

## Quality

Each pack carries test questions with known answers: comparisons between two periods, top N rankings, filters, monthly trends, and questions that should be clarified, refused or declined as off-topic. The evaluation scores each step separately (the type of question, what was extracted, what was found in the search index and whether the result matches) and compares result sets rather than SQL text.

| Pack | Industry | Correct results | Report |
| --- | --- | --- | --- |
| `ecommerce_twin` | E-commerce | 42 of 45 (93%) | [report](docs/eval/spec-building-fixes-report.md) |
| `iowa_liquor` | Spirits wholesale | 30 of 35 (86%) | [report](docs/eval/spec-building-fixes-report.md) |

```bash
docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin --output-dir build/eval
```

![Every run is traced](docs/architecture/tracing.svg)

Every run is logged in ClickHouse for 90 days: each step, SQL attempt, model call with its estimated cost, and access decision. [docs/tracing.md](docs/tracing.md) shows how to read one trace.

## Development

Use Python 3.13 with uv 0.13.6 and Node 24.21.0 with npm 11. Stop the Compose `api` and `web` services before running them on your machine, because they use the same ports.

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
```

```bash
npm --prefix apps/web ci
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
npm --prefix apps/web run dev
```

Unit tests replace every AI model and search call with a fake, so they need no key. Set `ACTIVE_PACK` before starting the web app; in development, `/dev/components` shows the design system. Commit dependency changes together with `apps/api/uv.lock` or `apps/web/package-lock.json`.

| Folder | Contents |
| --- | --- |
| [apps/api](apps/api) | API, agent and its prompts |
| [apps/web](apps/web) | Chat app and workspace console |
| [packs/](packs/README.md) | Domain Packs and their schemas |
| [dbt/](dbt/README.md) | Models that turn raw tables into the tables the agent reads |
| [jobs/](jobs/README.md) | Commands for loading data, publishing packs, onboarding and evaluation |
| [infra/](infra/README.md) | Service configuration |
| [docs/](docs) | Design notes and evaluation reports |

### Contributing

Branch from `develop` and open a pull request back to it. [CONTRIBUTING.md](CONTRIBUTING.md) describes the branch and commit message format, and [SECURITY.md](SECURITY.md) explains how to report a vulnerability.

## Data and licences

Datasets are never committed; downloads stay in the Git-ignored `data/` folder. FreeEcommerceTwin14M is licensed CC BY-NC 4.0 for non-commercial use. Iowa Liquor Sales 2025 is published by the Iowa Department of Revenue under CC BY 4.0.
