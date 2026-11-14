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
| See only your data | Each user works under a role. A question about data the role may not read is refused before any SQL is written, and the database enforces the same rules. |
| Stay safe | Every question is screened for prompt injection before it reaches an AI model. For now the screener records its verdict and lets the question through; blocking is switched on once it is accurate enough in both languages. |
| Check the work | Each answer shows the SQL it ran and the steps it took, and admins can open the full trace of any run. |
| Add a new company | fitcher profiles the company's tables, reads its documents and drafts a pack. A reviewer approves each item before it goes live. |
| Measure quality | Each pack has a set of test questions with known answers. A pack goes live only when at least 80% of them return the right result. |

The web app has a chat for everyone and a workspace console for reviewers and admins, in English and Vietnamese, light and dark themes, on desktop and phone.

## How it works

![How the pieces fit together](docs/architecture/system.svg)

The user talks to the web app, which streams answers from the API. One person uses it without signing in; a team signs in with accounts the API keeps, or through the company's OpenID Connect provider. The API runs the agent: it looks up the company's terms in the search index, sends language tasks to the AI models an admin connected in the app, and runs SQL in ClickHouse as the user's role. Models are called by task (fast replies, simple SQL, harder SQL), any task can use any model of a connected provider, and the pack's test results are shown next to each model. Search uses the provider's embedding model, or a local one when the provider has none. All of these services run together with Docker Compose on one machine.

![How a question is answered](docs/architecture/question-flow.svg)

A question goes through a safety check first. The agent then works out what is being asked, matches the words to the company's metrics, checks that the question is clear and permitted, writes one read-only query, validates and runs it, and picks a chart. If the query fails, the agent fixes it and tries again up to three times; if it still fails, you see the last SQL and the error. Each step shows on screen as it happens, and the numbers in the answer always come from the database, never from the AI model.

The recording below shows one question in the app going through these steps, each lit on the diagram as it runs, with the graph nodes it passed. It then opens the SQL the answer ran, and a follow-up chart change takes the quick-reply path without querying again.

![A question in the app going through the steps of the diagram, then its SQL and a chart change](docs/media/fitcher-question-flow.gif)

![Who can see what](docs/architecture/access-control.svg)

Each company's access rules live in one policy file. Publishing the pack turns it into database roles, column grants, row filters and aggregate-only views, so the database itself stops a role from reading what it should not. Every allow and deny decision goes to the audit log. The role-aware search only keeps the AI's context small and relevant; the database's own grants and row filters are what enforce access.

| Component | Technology |
| --- | --- |
| Web app | Next.js, ECharts, TanStack Table |
| Sign-in | Accounts kept by the API (Argon2id, server-side sessions); optional OpenID Connect provider |
| API and agent | FastAPI with streamed responses, LangGraph, sqlglot |
| AI models | OpenAI, Anthropic, Gemini, a local Ollama model or any OpenAI-compatible endpoint, called in process through the LiteLLM SDK; the provider's embedding model, or a local multilingual one with fastembed |
| Data and run logs | ClickHouse |
| Search index | Qdrant, combining meaning-based and keyword search |
| Data modelling | dbt |
| Domain Packs | YAML checked against JSON Schema |

## Where fitcher is going

Today fitcher runs as four services from this repository; models are connected in the application (Phase 14) and sign-in is built into the API (Phase 15). The next phases turn it into one image that starts with a single `docker run`, with data sources set up in the application instead of in files: see the [assessment](docs/self-hosted-product-assessment.md) (in Vietnamese), the [decisions](docs/DECISIONS.md) and the [master plan](docs/MASTER_PLAN.md), Phases 13 to 21. The Quick start below describes the current four-service setup.

## Quick start

You need Docker with Compose v2 and about 8 GB of memory for Docker. Run the commands from the repository root, in Bash or PowerShell.

1. Copy [.env.example](.env.example) to `.env` and replace every `change-me` value. Never commit `.env`. You add a model provider in the app's setup (step 4); to script it instead, set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `OLLAMA_URL` in `.env`, which creates that provider on the first start.

2. Start the services. They all report healthy before any model provider is connected.

   ```bash
   docker compose up --build --wait
   ```

3. Create the development accounts with the password set as `DEV_ACCOUNT_PASSWORD` in `.env`. This also puts the instance in team mode, where everyone signs in. Skip it to use the app alone without signing in (individual mode).

   ```bash
   docker compose run --rm jobs python -m jobs.seed_dev_accounts
   ```

4. Open [localhost:3000](http://localhost:3000) and sign in as `lab.admin@fitcher.test`. The setup asks who uses the instance and which models to use: a provider and its key, or a model server on this computer (Ollama, LM Studio or any OpenAI-compatible endpoint, reached as `host.docker.internal`). Its test call shows the model each task will use.

5. Load the sample e-commerce data and build the tables the agent reads. This downloads [FreeEcommerceTwin14M](https://huggingface.co/datasets/ziadatalabs/FreeEcommerceTwin14M), 14.3 million rows licensed for non-commercial use only. On Linux, `./data` must be writable by user ID 10001.

   ```bash
   docker compose run --rm jobs python -m jobs.refresh_data --source ecommerce_twin
   ```

6. Publish the e-commerce Domain Pack. This checks it, test-runs its metrics, writes the database permissions and builds the search index with the embedding model of the provider from step 4, which costs a little with a hosted provider. With a provider that has no embedding model, such as Anthropic alone, a local model is downloaded once (about 0.2 GB) instead; it finds fewer matches ([measurement](docs/eval/local-embedding-report.md)).

   ```bash
   docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin
   ```

7. Optionally, install the prompt-injection classifier. Questions are always screened by English and Vietnamese rules; the classifier adds a model score. Accept the licence of `meta-llama/Llama-Prompt-Guard-2-86M` on Hugging Face, put your token in `.env` as `HF_TOKEN`, run the command below and turn the classifier on on the Models page.

   ```bash
   docker compose run --rm guard-model
   ```

8. Sign in as `lab.analyst@fitcher.test` and pick one of the suggested questions. A hosted provider bills every question.

You can also ask from the command line:

```bash
docker compose run --rm api python -m jobs.ask "Top 10 best-selling products in Q1 2024 compared with Q1 2025"
```

`make up`, `make ps`, `make logs`, `make smoke` and `make down` are shortcuts for the Compose commands. Stopping the services keeps the data.

### Development accounts

Each signs in with its e-mail, `<user>@fitcher.test`, and `DEV_ACCOUNT_PASSWORD`.

| User | What they can see |
| --- | --- |
| `lab.analyst` | All sales, returns and site traffic |
| `lab.marketing` | Site traffic only, so a sales question is refused |
| `lab.northwest` | Sales and returns of the Northwest region only |
| `lab.partner` | Daily sales and units by product category, never single orders |
| `lab.reviewer` | What the analyst sees, plus the console's Review, Documents, Datasets, Feedback and Evaluation pages |
| `lab.admin` | What the analyst sees, plus Runs and trace, Audit, Costs, Models and Users |

### Services

| Service | Address |
| --- | --- |
| Web app | [localhost:3000](http://localhost:3000) |
| API | [localhost:8000](http://localhost:8000/health), with interactive [API docs](http://localhost:8000/docs) |
| Qdrant | localhost:6333 |
| ClickHouse | localhost:8123 (HTTP) and localhost:9000 (native) |

All ports listen on the local machine only.

## Using the API

The API streams each answer as server-sent events. In individual mode a request from the local machine needs no sign-in; in team mode, sign in once to get the session cookie and send it with each request. In individual mode a request that changes something must name the page it comes from in `Origin`, which the example sends in both modes:

```bash
curl -s -c fitcher.cookies -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:8000" -d "{\"email\":\"lab.analyst@fitcher.test\",\"password\":\"$DEV_ACCOUNT_PASSWORD\"}" http://127.0.0.1:8000/session
curl -N -b fitcher.cookies -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:8000" -d '{"question":"Top 10 best-selling products in Q1 2024 compared with Q1 2025","timezone":"Asia/Ho_Chi_Minh"}' http://127.0.0.1:8000/ask
```

The stream reports each step as it starts and finishes, then sends the SQL, the result, the chart and the summary. A question that cannot be answered ends with a clarifying question, a refusal, a blocked notice or an error instead. The response names the conversation it started; send that id with the next question to ask a follow-up. Closing the connection stops the run and its database query.

Each user may ask 10 questions a minute by default. The same API manages conversations (list, search, rename, pin, group and delete), records likes and dislikes, and serves the console's admin pages. The [API docs](http://localhost:8000/docs) of a running stack list every endpoint.

## Bringing in a new company

![Bringing in a new company](docs/architecture/onboarding.svg)

A new company needs its own Domain Pack and nothing else. The Iowa Liquor Sales pack was built this way from a PostgreSQL database.

1. Connect the company's PostgreSQL, MySQL, MongoDB or file sources. ClickHouse either copies the data on a schedule or reads it live, and only ClickHouse holds the read-only credentials.
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
