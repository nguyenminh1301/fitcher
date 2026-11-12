# Phase 9B: Input screening

## Goal

Screen every untrusted input before it reaches an LLM (DECISIONS §9 Layer 0): EN/VI rules and a local prompt-injection classifier score each new question and each indexed document chunk, a `blocked` reply ends a run whose question crosses the threshold, the LiteLLM gateway rejects any request the api did not screen, and a local measurement shows the false-positive rate and recall per language before blocking is switched on.

## Scope

- The screening module in `api`: rules, the ONNX classifier, verdicts and modes.
- Fetching and converting the classifier model outside Git.
- The `screen` graph node, the `blocked` stream event and the `input_screening` log table.
- The gateway guardrail and the `screening` request metadata.
- Instructions in `system` messages and untrusted content in `user` messages, with new prompt versions.
- Screening of document chunks and column values when the compiler indexes them.
- The measurement job with its benign and attack sets.
- The web notice for a blocked question.

## Out of scope

- Scanning model output, for example a leaked system prompt.
- Fine-tuning or training the classifier.
- Showing screening verdicts in the console (Phase 12 Audit page).
- Screening uploads through the Documents API, which does not exist yet; Phase 10 calls this phase's screening function there.

## Prerequisites

- Phases 7, 8 and 9: the streaming api, conversations and the wired chat answers.
- The owner accepts the Llama 4 licence for `meta-llama/Llama-Prompt-Guard-2-86M` on Hugging Face and puts an access token in `.env` as `HF_TOKEN`; it is never committed.

## Deliverables

```text
apps/api/app/screening/
  rules.py                          # EN/VI rules on folded text, versioned
  classifier.py                     # ONNX Runtime wrapper, 512-token windows, max score
  screen.py                         # screen(text, source) -> Verdict(verdict, score, rule_hits, model_version)
apps/api/app/agent/nodes/screen.py  # first graph node; block -> blocked reply
apps/api/app/contracts/events.py    # BlockedEvent
apps/api/app/llm/client.py          # system/user messages, screening metadata
apps/api/prompts/*.vN.md            # new versions split into system and user parts
apps/api/app/packs/compiler.py      # screen kb_docs chunks and column values while indexing
jobs/fetch_guard_model.py           # download with HF_TOKEN, convert to ONNX into the guard_models volume
jobs/screen_eval.py                 # benign and attack sets -> per-language report
apps/api/tests/screening/benign.yaml attacks.yaml
infra/litellm/callbacks/screening_guard.py   # pre_call guardrail
infra/litellm/config.yaml           # guardrail registration
infra/clickhouse/initdb/010-agent-logs.sql   # agent_logs.input_screening, plus jobs/apply_log_schema.py
compose.yaml                        # guard_models volume on api; SCREEN_* settings
apps/web/components/chat/answer-parts.tsx    # blocked notice
apps/web/lib/contracts/             # regenerated event types
```

## Tasks

1. **Rules (test first).** Fold text (NFKC, lower case, Vietnamese diacritics removed, whitespace collapsed) and match high-precision patterns in English and Vietnamese: requests to ignore or replace earlier instructions, to reveal the system prompt or hidden context, role-play as the system or developer, and fake prompt boundaries (`</question>`, `<|im_start|>`, `### system`, `[INST]`). A rule hit yields `block`. Tests cover each pattern with and without diacritics and a set of benign questions that mention "instructions" or "system" in normal business use.
2. **Classifier wrapper (test first).** Load the ONNX model and tokenizer with `onnxruntime` and `tokenizers`; split long text into overlapping 512-token windows and return the highest malicious score; report the model version. Unit tests use a fake classifier; one optional test runs the real model when the volume has it.
3. **Verdicts and modes.** `screen(text, source)` combines rules and score into `allow`, `flag` (score >= `SCREEN_FLAG_AT`, default 0.5) or `block` (rule hit or score >= `SCREEN_BLOCK_AT`, default 0.9). `SCREEN_MODE=log` (default) records the verdict and lets the run continue; `enforce` stops a `block`. Without a loaded classifier the result is `unavailable`, which stops the run in both modes (fail closed).
4. **Model fetch job.** `jobs/fetch_guard_model.py` downloads the model with `HF_TOKEN`, converts it to ONNX, checks it against a few known inputs and writes it with its version to the `guard_models` volume. It never prints the token.
5. **Graph node and contract (test first).** `screen` runs first and writes one `input_screening` row per question. `block` (enforce) or `unavailable` emits `BlockedEvent {message, lang, trace_id}` in the question's language and ends with `done`; the blocked question is not stored as a conversation turn. Tests cover the stream order `status* -> blocked -> done` for both causes, log mode letting a `block` continue, and `flag` continuing.
6. **Log table.** `agent_logs.input_screening(trace_id, ts, user_id, source, verdict, mode, score, rule_hits, model_version)` with the 90-day TTL, created on a fresh volume and applied to an existing one by `jobs/apply_log_schema.py`; the log writer already holds `INSERT ON agent_logs.*`.
7. **System and user messages.** The LLM client takes instructions and untrusted content separately and sends a `system` and a `user` message; every prompt gets a new version that keeps its rules in the system part and its data (question, history, definitions, rows) in the user part. Every request carries `screening` metadata from the run (`allow` or `flag`); compile-time calls carry `trusted_pack`.
8. **Gateway guardrail (test first).** `screening_guard.py` runs in `pre_call` mode, rejects a request without `screening` metadata with a clear error and reruns the rules on every message as a safety net. It keeps its own copy of the rules (the LiteLLM image does not import `apps/api`); a test fails when the two copies differ. The api maps a gateway rejection to the `blocked` reply.
9. **Compile-time screening.** While indexing, the compiler screens every `kb_docs` chunk (a `block` chunk is not indexed and is listed in the compile report) and every low-cardinality column value (reported only, still indexed).
10. **Measurement job.** `jobs/screen_eval.py` runs locally and makes no LLM call. It screens the benign set (the active pack's eval questions and sample suggestions plus an engine-level EN/VI benign set) and the attack set (about 100 hand-written EN/VI cases, direct and inside document text) and prints false-positive rate and recall per language, with the misclassified items.
11. **Health.** `/health` stays a liveness check and reports `screening: ready | unavailable` with the classifier version, so Compose and CI do not depend on the gated model.
12. **Web notice.** The `blocked` event shows a `NoticeCard` written in the answer's language that never repeats the blocked text; the step list shows "Checking the question".

## Contracts

- `BlockedEvent`: `{event: "blocked", message, lang, trace_id}`; TypeScript types regenerated from Pydantic.
- Request metadata `screening`: `allow | flag | trusted_pack`.
- Settings: `SCREEN_MODE`, `SCREEN_FLAG_AT`, `SCREEN_BLOCK_AT`, `HF_TOKEN` (job only), `GUARD_MODEL_DIR`.
- `agent_logs.input_screening` as in task 6.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web ci
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
docker compose up --build --wait
docker compose run --rm api python -m jobs.fetch_guard_model
docker compose run --rm api python -m jobs.screen_eval --pack ecommerce_twin
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

## Definition of done

| DoD item | Proof |
|---|---|
| In log mode an attack question is answered and logged as `block`; in enforce mode it gets the `blocked` notice and no LLM call | Integration test with a fake classifier; `llm_calls` has no row for the trace |
| Without the classifier every question gets the "screening unavailable" notice and no LLM call | Test with the classifier missing |
| A request without screening metadata is rejected by the gateway | Guardrail test |
| The measurement is attached | `screen_eval.py` report in the PR, per language |
| The prompt split does not regress the agent | Pack eval report against the baseline |

## Risks and open questions

1. **Vietnamese false positives.** The classifier's listed training languages do not include Vietnamese. Default: stay in log mode until the DECISIONS §9 gate holds in both languages; tune thresholds and rules from the report instead of enforcing early.
2. **Gated model in CI.** Default: CI never downloads the model; unit tests use the fake classifier and the real-model test is skipped without the volume.
3. **Latency.** Default: one classifier pass per question on CPU, measured in the PR; windows are capped at 8 per question.
4. **Licence.** The Llama 4 licence binds the deployment; the owner accepts it on Hugging Face. The repository stores no weights.

## Web wiring

| Feature | Mock to retire | Real endpoint | Contract | Done when |
|---|---|---|---|---|
| `chat` | none (the sample chat has no blocked scenario) | `POST /ask` `blocked` event | `AskEvent` | The http chat renders the blocked notice; a sample scenario with a blocked question is added to the pack's sample data for the demo |

## Branch and PR split

- `feat/agent/screen-untrusted-input`: tasks 1-4 and 10.
- `feat/agent/block-screened-questions`: tasks 5-7 and 11, with the pack eval run.
- `feat/infra/reject-unscreened-llm-requests`: tasks 8-9.
- `feat/web/show-blocked-questions`: task 12.
