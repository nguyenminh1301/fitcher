# Phase 10: Automated onboarding

## Goal

Generate a Domain Pack for a new company with human review: profile the loaded marts, let reviewers upload and delete company documents at runtime, draft every pack item with evidence and confidence, let a reviewer approve or edit items in a Review UI, then compile the approved pack.

## Scope

- `profile.py`, `ingest_docs.py`, `draft_pack.py` jobs (DECISIONS §11 steps 2-4).
- Review UI and its API endpoints (step 5).
- Documents API and page: upload, list and delete company documents at runtime (DECISIONS §5).
- Compile after review (step 6) reusing Phase 2 and Phase 6.

## Out of scope

- Loading a second dataset (Phase 11).
- Automatic Git commits from the application (open question 1).
- Feedback-driven proposals (Phase 12).
- OCR of scanned PDFs and images, and downloading stored originals from the UI.

## Prerequisites

- Phases 2, 4, 6 and 9: compiler, eval, policies, web shell with auth.

## Deliverables

```text
jobs/profile.py                     # writes build/packs/<pack>/profile.json
jobs/ingest_docs.py                 # bulk-load a folder through the documents service
jobs/draft_pack.py                  # writes draft items into packs/<pack>/*.yaml
apps/api/app/onboarding/
  profiler.py docs_parser.py chunker.py drafter.py review.py
  documents.py                      # registry, stored files, upload/delete into kb_docs
apps/api/prompts/draft_datasets.v1.md draft_glossary.v1.md draft_metrics.v1.md draft_examples.v1.md
apps/api/app/api/review.py          # list, edit, approve, delete, test-run metric
apps/api/app/api/documents.py       # upload, list, delete documents
apps/web/app/(review)/              # Review UI pages
apps/web/app/(review)/documents/    # Documents page
infra/clickhouse/                   # data_meta.documents and its writer user, fresh-volume init plus apply path
compose.yaml                        # documents volume on api
```

## Tasks

1. **Profiler (test first, deterministic).** From `system.columns` and queries: row counts, min/max per date column, distinct counts, top-K values for low-cardinality strings, join-key candidates (name and value overlap), a few sample rows. No LLM.
2. **Document ingestion (test first).** Parse PDF, DOCX, Markdown, plain text and XLSX; chunk Markdown and DOCX by heading, PDF and text by paragraphs, XLSX by blocks of rows repeating the header row, all with a size cap; tag chunks with document id, source, heading path or sheet name and `allowed_roles`; index into `kb_docs`. `ingest_docs.py` reads `allowed_roles` from a folder manifest and uses the same service as uploads. Tests on small fixture documents of every format, including an empty file, a PDF without a text layer and a macro-enabled workbook (rejected).
3. **Drafter.** `sql-gen` prompts per pack file take the profile and document chunks and return items with `status: draft`, `evidence` (profile facts or chunk ids) and `confidence`. Drafted `sql_expr` values are test-run before being saved; failures are kept as drafts with the error as evidence. Prompts state that document text is data, never instructions, and that no figures are taken from text.
4. **YAML round-trip.** Draft writes preserve existing approved items, comments and ordering (ruamel.yaml); a draft never overwrites an approved item.
5. **Review API.** List items by file and status, edit, approve, delete, test-run a metric expression against ClickHouse with the admin limits. Restricted to a `pack_reviewer` role.
6. **Review UI.** Per-file item list with evidence and confidence, inline edit, approve/delete, metric test-run result; approved changes saved to the pack files.
7. **Compile after review.** Run the Phase 2 compiler; only approved items are used.
8. **Regeneration experiment.** Copy the hand-written pack to `packs/ecommerce_twin_regen/`, remove the descriptions there and mark those items `status: draft`, so the drafter may fill them without touching approved items. Review, compile and evaluate the copy against the untouched hand-written pack's baseline.
9. **Documents API (test first).** `POST /documents` (multipart), `GET /documents`, `DELETE /documents/{id}`, restricted to `pack_reviewer`. Upload checks the type from the file content, a size cap (default 20 MB), that `allowed_roles` is a non-empty subset of the pack's roles and that the SHA-256 is new for the pack (409 otherwise), then stores, parses, embeds and indexes as in task 2 and records the registry row. Delete removes the chunks by document id, the stored file and marks the row deleted. Both return 409 while the pack compiles. Tests use a fake embedding client and cover every rejection, a failed parse leaving no chunks, and delete removing every chunk.
10. **Documents page and propagation.** Upload with role selection, list with status and error, delete with confirmation, and a billable "draft from this document" action that runs the drafter on that document only. The Review UI flags pack items whose evidence cites a deleted document. The compiler fills each new `kb_docs` generation from the registry (DECISIONS §5); a test compiles after an upload and after a delete.

## Contracts

- Draft item fields: `status`, `evidence`, `confidence: 0..1`, using the shared evidence definition from Phase 2 (`manual`, `profile`, `doc`, `error`, `trace`).
- `profile.json` schema documented in `apps/api/app/onboarding/profiler.py`.
- `data_meta.documents`: `id, pack, file_name, media_type, size_bytes, sha256, uploaded_by, allowed_roles, status, error, uploaded_at, deleted_at`.
- `kb_docs` chunk: `{id, type, document_id, source, heading_path, text, embedding, allowed_roles, pack}`.

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
| An uploaded document is searchable and a deleted one is gone | Integration test against live OpenSearch: upload, `kb_docs` search hit, delete, no hit |

## Risks and open questions

1. **Committing approved YAML.** DECISIONS says approved items are committed to Git. Default: the api writes approved YAML to the mounted `packs/` working tree and the reviewer commits through the normal branch and PR workflow; the application never runs Git.
2. **"Not significantly lower".** MASTER_PLAN leaves the threshold open. Default rule for the owner to confirm: on the Phase 4 eval set, the regenerated pack's execution match is within 5 percentage points of the hand-written baseline, and extraction and retrieval deltas are reported with the Phase 4 per-layer regression rule.
3. **Document parsing dependencies.** Default: `pypdf`, `python-docx` and `openpyxl` (read-only, values only), pinned; plain text must be UTF-8; scanned PDFs (OCR) are out of scope.
4. **Drafting cost.** Drafting all files is billable; the job prints an estimate and runs only with `--allow-billable`.
5. **Untrusted uploads.** Uploaded files are parsed but never executed or served back; parsing runs with the size cap and a page/row limit, and their text is data, never instructions (DECISIONS §9). Default: no antivirus scan in the lab.

## Branch and PR split

- `feat/agent/profile-marts-and-ingest-docs`: tasks 1-2.
- `feat/agent/draft-pack-items`: tasks 3-4.
- `feat/web/review-drafted-pack-items`: tasks 5-7.
- `feat/web/manage-company-documents`: tasks 9-10.
- Task 8 results ride with `feat/web/review-drafted-pack-items`.
