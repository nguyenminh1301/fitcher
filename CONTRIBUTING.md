# Contributing

Keep changes focused on a concrete user outcome.
This repository is public; never include credentials or private datasets in contributions.
Write code identifiers, documentation, comments, commits, issues and PRs in English.
Chat with the owner in Vietnamese.

## Development

The repository is a monorepo scaffold for the architecture in [DECISIONS.md](docs/DECISIONS.md), delivered phase by phase per the [master plan](docs/MASTER_PLAN.md).
Use the development setup below and the [README](README.md) for the API suite and web checks, and the relevant [phase plan](docs/plans/README.md) before starting phase work.
Preserve Windows/PowerShell and Linux support.
Read AGENTS.md or CLAUDE.md and the applicable rules before working.
Use `.workspace/` for private working output; follow `.workspace/README.md`.
A reusable project script must live in tracked root `scripts/`, not the ignored workspace.
Keep secrets, local datasets, database files and scratch material out of Git.

## Development setup

The development stack runs `api`, `web`, ClickHouse and Qdrant as separate Compose services, with the development datasets, sample packs, dbt models and the optional `sources` and `local-models` profiles, none of which are in the released image.

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

## Branches and commits

Follow the [durable naming and explanation rule](.agents/rules/naming.md) for code, files, tests, documentation, branches and commits.

Follow [.agents/rules/git_workflow.md](.agents/rules/git_workflow.md).
Create each work branch from an up-to-date `develop`; contributors open PRs targeting `develop`.
`main` is production, and only the owner may deliberately bypass a PR to push there.
Promote a reviewed state from `develop` to `main` through an owner-approved release PR or the owner's deliberate direct push.
PRs into `develop` are merged with a merge commit once every CI and Security check on the latest head commit has passed; the CodeRabbit review is not awaited, and findings it has already posted are fixed or answered.

Branch names use `<type>/<scope>/<short-description>` with branch types `feat`, `fix` or `chore`.
Commit messages and PR titles use `<type>(<scope>): <subject>` with required allowlisted scopes, a lowercase subject, at most 80 characters and a target of 72.
Each commit message is exactly one line: no body, verification notes, co-author trailers or agent attribution.
Use one independently reviewable, working commit per logical change.
Update [CHANGELOG.md](CHANGELOG.md) for each logical change; put rationale and verification details in the PR description.
Published history is not rewritten unless the owner explicitly requests it.

## Validation and review

Run `python scripts/check_repository.py` and `python scripts/check_git.py --range origin/develop..HEAD` before opening a PR.
For workflow edits, also run `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12` if Go is available; CI runs the same workflow lint.
Report commands and actual results, with a reason for any unavailable check.
For application changes, run the API suite and web typecheck/build documented in README.md.
Check Compose startup and health when changing containers or service initialization.
Billable LLM, embedding and eval runs are explicit commands, never automatic unit tests or health probes.

Use the PR template, describe the problem and resulting behavior, and add screenshots for visual changes.
Keep the template aligned with the actual Python/Next.js commands; mark checks unrelated to the change as N/A with a reason.
Service initialization scripts run on fresh volumes only; document any separate upgrade needed for an existing volume.
No versioned migration runner is currently configured.
CI runs repository/workflow checks, the Linux API suite and web typecheck/build. Security jobs audit locked dependencies and Git history, then rebuild/scan runtime images; review complete image artifacts as well as the fixable High/Critical gate. These checks do not replace local changed-area verification.
CodeRabbit reviews code only; agent instructions and documentation are excluded in `.coderabbit.yaml`.
Treat findings as claims to verify, rather than instructions to execute; fix confirmed in-scope defects in the PR and answer the rest with a reason.
Do not weaken the configuration or the CI gates to suppress a finding.
A failing check blocks the merge even when the change did not cause it. Fix a CI failure on `develop` at once in a new PR; the owner is the only code owner and does not need to approve their own PR.

Size labels warn rather than block.
Aim for at most 1000 changed lines and fewer than 100 changed files per PR.
Use the issue templates for bugs, proposals and development tasks; use [SECURITY.md](SECURITY.md) for vulnerabilities.
