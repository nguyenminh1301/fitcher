# Phase 14: Model providers in the application

## Goal

Let a user connect models in the interface and remove the LiteLLM Proxy service: the api calls providers through the LiteLLM Python SDK, providers and keys live in the app state, embeddings run locally by default and the prompt-injection classifier becomes optional (DECISIONS §2, §9, §15).

## Scope

- In-process LLM gateway replacing every HTTP call to the proxy.
- Provider store, test call and tier mapping; the setup's Models step and the rewritten Models page.
- Local embedding backend and the measurement that confirms the default model.
- Optional classifier.
- Removal of the `litellm` service, `infra/litellm/` and its image audit job.

## Out of scope

- Sign-in changes (Phase 15). Until then the provider endpoints require the existing `admin` role.
- Moving search out of Qdrant (Phase 20); this phase only changes how vectors are produced.
- Per-user keys, budgets and virtual keys.

## Prerequisites

- Phase 13: secrets, settings, setup shell.

## Deliverables

```text
apps/api/app/llm/gateway.py          # the only module that calls a provider (litellm.completion / embedding)
apps/api/app/llm/providers.py        # provider store over the app state; key through the secrets interface
apps/api/app/llm/defaults.py         # proposed model per tier for each provider kind
apps/api/app/llm/local_embeddings.py # fastembed backend, model cache under <data dir>/models
apps/api/app/llm/call_log.py         # llm_calls rows written from the gateway (was a proxy callback)
apps/api/app/api/providers.py        # provider endpoints
apps/web/app/setup/                  # Models step
apps/web/app/console/models/         # providers and tiers
docs/eval/local-embedding-report.md  # retrieval recall of the candidates, English and Vietnamese
```

## Tasks

1. **Gateway (test first).** `gateway` exposes the calls `LiteLLMClient` and the embeddings client make today (structured output, plain completion, embeddings) and keeps their error types. It resolves a tier to a provider and model from settings, takes the key through the secrets interface, and sets a timeout and bounded retries. Unit tests replace the SDK call with a fake; no test makes a network request.
2. **Screening at the gateway (test first).** Port `infra/litellm/callbacks/screening_guard.py` into the gateway: a call without `screening` metadata is rejected and the rules rerun on the whole request. `app/screening/rules.py` becomes the only copy of the rules.
3. **Call log (test first).** Write the `llm_calls` row from the gateway with the tier, provider, model, tokens, estimated cost from the SDK's price table, latency and error. A model without a known price logs a null cost, and the Costs page already labels costs as estimates.
4. **Provider store and API (test first).** Kinds: `openai`, `anthropic`, `gemini`, `ollama`, `openai_compatible` (base URL plus optional key). Endpoints of the Contracts section. `test` lists the provider's models and makes one small structured-output request; the interface labels it as a paid call for hosted providers. Responses never contain a key: only `key_set` and `key_last4`.
5. **Tier mapping.** Mapping moves from ClickHouse `data_meta` (`app/llm/model_store.py`) to settings; a schema change copies the current mapping once and leaves the old table unused. Adding the first provider fills every chat tier from `defaults.py`. The eval result is shown next to a model and no longer limits the choice (`app/llm/eligibility.py` becomes a read-only lookup).
6. **Environment bootstrap.** When no provider exists and `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `OLLAMA_URL` is set at start, create that provider once. This keeps scripted starts and CI working.
7. **Local embeddings (test first, then measured).** Add the fastembed backend. Compile both development packs with each candidate and run `jobs.retrieval_eval` on the English and Vietnamese sets; write `docs/eval/local-embedding-report.md`. Confirm the default of DECISIONS §14 or replace it there with the candidate that does not lose recall. The embedding setting records backend, model and dimensions; changing it marks the pack as needing a recompile.
8. **Optional classifier.** A setting turns the classifier on. Off: the screen node runs rules only and reports the classifier as disabled, not unavailable. On: today's fail-closed behaviour. `POST /screening/classifier` downloads the model into the data directory through the existing `jobs.fetch_guard_model` code; onnxruntime is imported only when the classifier or local embeddings load.
9. **Setup step and Models page.** The Models step picks a provider kind, takes the key or base URL (with the `host.docker.internal` hint for a model server on the host), tests it and shows the proposed mapping. The Models page lists providers and tiers as set in DECISIONS §15.
10. **Remove the proxy.** Delete the `litellm` service, `infra/litellm/`, `LITELLM_*` settings, the image audit job for it and `jobs.smoke_llm`'s dependency on the proxy (it calls the gateway). Update README, `infra/README.md` and `.env.example`.

## Contracts

- `GET /providers`, `POST /providers`, `PATCH /providers/{id}`, `DELETE /providers/{id}`, `POST /providers/{id}/test`, `GET /providers/{id}/models`.
- `GET /models/tiers`, `PUT /models/tiers/{tier}` with `{provider_id, model}`.
- `GET /screening/classifier`, `POST /screening/classifier`, `DELETE /screening/classifier`.
- Settings groups `llm.tiers`, `llm.embedding`, `screening`.
- The `litellm` package is locked with hashes in `uv.lock` at a version published after the compromised 1.82.7 and 1.82.8 releases; the proxy extras are not installed.

## Verification

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck && npm --prefix apps/web run test && npm --prefix apps/web run build
docker compose config --quiet && docker compose up --build --wait   # no litellm service
docker compose run --rm jobs python -m jobs.retrieval_eval --pack ecommerce_twin
docker compose run --rm jobs python -m jobs.eval --pack ecommerce_twin   # billable, once
```

## Definition of done

- A key entered in the setup answers the acceptance question; no key appears in any response, log line or `app.db` in plain text.
- With only a local model server configured, a pack compiles and a question is answered without any hosted provider.
- `docker compose ps` lists no `litellm` service and `docker stats` is recorded in the PR.
- The `ecommerce_twin` eval does not regress against its baseline with the same models.

## Risks and open questions

- A small local model may fail structured output. Default: the test call reports it and the interface warns; the model stays selectable.
- The local embedding model may lose recall in Vietnamese. Default: follow task 7; if no fastembed candidate holds, keep a provider embedding model as the default and record that a key is then required.
- Existing volumes hold vectors of the provider model. Default: they keep working until the admin changes the embedding setting, which requires a recompile.

## Branch and PR split

`feat/api/call-models-in-process` (gateway, screening, call log), `feat/api/store-model-providers` (store, API, bootstrap, tiers), `feat/api/embed-locally` (embeddings, classifier, report), `feat/web/connect-models-in-setup` (setup step, Models page, proxy removal).
