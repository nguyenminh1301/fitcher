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

The user talks to the web app, which signs them in through Keycloak and streams answers from the API. The API runs the agent: it looks up the company's terms in the search index, sends language tasks to AI models through the LiteLLM gateway, and runs SQL in ClickHouse as the user's role. Models are called by task (fast replies, simple SQL, harder SQL, embeddings), and an admin can switch a task to another model once that model passes the pack's test questions. All of these services run together with Docker Compose on one machine.

![How a question is answered](docs/architecture/question-flow.svg)

A question goes through a safety check first. The agent then works out what is being asked, matches the words to the company's metrics, checks that the question is clear and permitted, writes one read-only query, validates and runs it, and picks a chart. If the query fails, the agent fixes it and tries again up to three times; if it still fails, you see the last SQL and the error. Each step shows on screen as it happens, and the numbers in the answer always come from the database, never from the AI model.

The recording below shows one question in the app going through these steps, each lit on the diagram as it runs, with the graph nodes it passed. It then opens the SQL the answer ran, and a follow-up chart change takes the quick-reply path without querying again.

![A question in the app going through the steps of the diagram, then its SQL and a chart change](docs/media/fitcher-question-flow.gif)

![Who can see what](docs/architecture/access-control.svg)

Each company's access rules live in one policy file. Publishing the pack turns it into database roles, column grants, row filters and aggregate-only views, so the database itself stops a role from reading what it should not. Every allow and deny decision goes to the audit log. The role-aware search only keeps the AI's context small and relevant; the database's own grants and row filters are what enforce access.

| Component | Technology |
| --- | --- |
| Web app | Next.js, ECharts, TanStack Table |
| Sign-in | Keycloak (OpenID Connect) |
| API and agent | FastAPI with streamed responses, LangGraph, sqlglot |
| AI model gateway | LiteLLM, with OpenAI, Anthropic, Gemini or a local Ollama model |
| Data and run logs | ClickHouse |
| Search index | Qdrant, combining meaning-based and keyword search |
| Data modelling | dbt |
| Domain Packs | YAML checked against JSON Schema |

## Quick start

You need Docker with Compose v2 and about 8 GB of memory for Docker. Run the commands from the repository root, in Bash or PowerShell.

1. Copy [.env.example](.env.example) to `.env`, replace every `change-me` value and add a key for at least one model provider (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OLLAMA_URL` with the `local-models` profile). Never commit `.env`.

2. Start the services. They all report healthy even before a model key is set.

   ```bash
   docker compose up --build --wait
   ```

3. Load the sample e-commerce data and build the tables the agent reads. This downloads [FreeEcommerceTwin14M](https://huggingface.co/datasets/ziadatalabs/FreeEcommerceTwin14M), 14.3 million rows licensed for non-commercial use only. On Linux, `./data` must be writable by user ID 10001.

   ```bash
   docker compose run --rm jobs python -m jobs.refresh_data --source ecommerce_twin
   ```

4. Publish the e-commerce Domain Pack. This checks it, test-runs its metrics, writes the database permissions and builds the search index, which costs a little in embedding calls.

   ```bash
   docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin
   ```

5. Install the prompt-injection classifier. Accept the licence of `meta-llama/Llama-Prompt-Guard-2-86M` on Hugging Face and put your token in `.env` as `HF_TOKEN`. Until the classifier is installed, every question is blocked.

   ```bash
   docker compose run --rm guard-model
   ```

6. Give the demo users the password set as `KEYCLOAK_LAB_USER_PASSWORD` in `.env`.

   ```bash
   docker compose run --rm jobs python -m jobs.set_lab_passwords
   ```

7. Open [localhost:3000](http://localhost:3000), choose Continue with company account, sign in as `lab.analyst` and pick one of the suggested questions. Every question is billed by your model provider.

You can also ask from the command line:

```bash
docker compose run --rm api python -m jobs.ask "Top 10 best-selling products in Q1 2024 compared with Q1 2025"
```

`make up`, `make ps`, `make logs`, `make smoke` and `make down` are shortcuts for the Compose commands. Stopping the services keeps the data.

### Demo users

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
| Keycloak | [localhost:8080](http://localhost:8080), realm `finch` |
| LiteLLM | localhost:4000 |
| Qdrant | localhost:6333 |
| ClickHouse | localhost:8123 (HTTP) and localhost:9000 (native) |

All ports listen on the local machine only.

## Using the API

The API streams each answer as server-sent events and needs a Keycloak access token. On a local setup, the `finch-cli` client issues one for a demo user:

```bash
TOKEN=$(curl -s -d grant_type=password -d client_id=finch-cli -d username=lab.analyst --data-urlencode "password=$KEYCLOAK_LAB_USER_PASSWORD" http://127.0.0.1:8080/realms/finch/protocol/openid-connect/token | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
curl -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Top 10 best-selling products in Q1 2024 compared with Q1 2025","timezone":"Asia/Ho_Chi_Minh"}' http://127.0.0.1:8000/ask
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
