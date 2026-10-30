# Phase 10: Automated onboarding

## Goal

Generate a Domain Pack for a new company with human review: profile the loaded marts, ingest company documents, draft every pack item with evidence and confidence, let a reviewer approve or edit items in a Review UI, then compile the approved pack.

## Scope

- `profile.py`, `ingest_docs.py`, `draft_pack.py` jobs (DECISIONS §11 steps 2-4).
- Review UI and its API endpoints (step 5).
- Compile after review (step 6) reusing Phase 2 and Phase 6.

## Out of scope

- Loading a second dataset (Phase 11).
- Automatic Git commits from the application (open question 1).
- Feedback-driven proposals (Phase 12).

## Prerequisites

- Phases 2, 4, 6 and 9: compiler, eval, policies, web shell with auth.

## Deliverables

```text
jobs/profile.py                     # writes build/packs/<pack>/profile.json
jobs/ingest_docs.py                 # parse, chunk by heading, index kb_docs, hand chunks to drafter
jobs/draft_pack.py                  # writes draft items into packs/<pack>/*.yaml
apps/api/app/onboarding/
  profiler.py docs_parser.py chunker.py drafter.py review.py
apps/api/prompts/draft_datasets.v1.md draft_glossary.v1.md draft_metrics.v1.md draft_examples.v1.md
apps/api/app/api/review.py          # list, edit, approve, delete, test-run metric
apps/web/app/(review)/              # Review UI pages
```

## Tasks

1. **Profiler (test first, deterministic).** From `system.columns` and queries: row counts, min/max per date column, distinct counts, top-K values for low-cardinality strings, join-key candidates (name and value overlap), a few sample rows. No LLM.
2. **Document ingestion (test first).** Parse PDF, DOCX and Markdown; chunk by heading with a size cap; tag chunks with source, heading path and `allowed_roles` (default from a manifest); index into `kb_docs`. Tests on small fixture documents.
3. **Drafter.** `sql-gen` prompts per pack file take the profile and document chunks and return items with `status: draft`, `evidence` (profile facts or chunk ids) and `confidence`. Drafted `sql_expr` values are test-run before being saved; failures are kept as drafts with the error as evidence. Prompts state that document text is data, never instructions, and that no figures are taken from text.
4. **YAML round-trip.** Draft writes preserve existing approved items, comments and ordering (ruamel.yaml); a draft never overwrites an approved item.
5. **Review API.** List items by file and status, edit, approve, delete, test-run a metric expression against ClickHouse with the admin limits. Restricted to a `pack_reviewer` role.
6. **Review UI.** Per-file item list with evidence and confidence, inline edit, approve/delete, metric test-run result; approved changes saved to the pack files.
7. **Compile after review.** Run the Phase 2 compiler; only approved items are used.
8. **Regeneration experiment.** Copy the hand-written pack to `packs/ecommerce_twin_regen/`, remove the descriptions there and mark those items `status: draft`, so the drafter may fill them without touching approved items. Review, compile and evaluate the copy against the untouched hand-written pack's baseline.

## Contracts

- Draft item fields: `status`, `evidence`, `confidence: 0..1`, using the shared evidence definition from Phase 2 (`manual`, `profile`, `doc`, `error`, `trace`).
- `profile.json` schema documented in `apps/api/app/onboarding/profiler.py`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
docker compose run --rm api python -m jobs.profile --pack ecommerce_twin
docker compose run --rm api python -m jobs.draft_pack --pack ecommerce_twin_regen --allow-billable
# review and approve the drafted items in the Review UI
docker compose run --rm api python -m jobs.compile_pack --pack ecommerce_twin_regen
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin_regen --baseline packs/ecommerce_twin/eval_baseline.json
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

## Definition of done

| DoD item | Proof |
|---|---|
| Regenerated and reviewed descriptions score not significantly lower than the hand-written pack | Eval comparison in the PR, within the agreed tolerance |

## Risks and open questions

1. **Committing approved YAML.** DECISIONS says approved items are committed to Git. Default: the api writes approved YAML to the mounted `packs/` working tree and the reviewer commits through the normal branch and PR workflow; the application never runs Git.
2. **"Not significantly lower".** MASTER_PLAN leaves the threshold open. Default rule for the owner to confirm: on the Phase 4 eval set, the regenerated pack's execution match is within 5 percentage points of the hand-written baseline, and extraction and retrieval deltas are reported with the Phase 4 per-layer regression rule.
3. **Document parsing dependencies.** Default: `pypdf` and `python-docx`, pinned; scanned PDFs (OCR) are out of scope.
4. **Drafting cost.** Drafting all files is billable; the job prints an estimate and runs only with `--allow-billable`.

## Branch and PR split

- `feat/agent/profile-marts-and-ingest-docs`: tasks 1-2.
- `feat/agent/draft-pack-items`: tasks 3-4.
- `feat/web/review-drafted-pack-items`: tasks 5-7.
- Task 8 results ride with the last PR.
