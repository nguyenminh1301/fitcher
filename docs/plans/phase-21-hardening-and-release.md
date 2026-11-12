# Phase 21: Hardening and first release

## Goal

Make the single image safe to hand to strangers and publish version 1.0: fix the known weaknesses in retention, concurrency and secrets handling, add backup and restore, review security end to end, publish the demo and rewrite the public documentation.

## Scope

- Conversation retention separated from log expiry.
- Concurrency limits and a load measurement.
- Security review of the new surfaces (setup, providers, sources, sign-in) and supply-chain pinning.
- Backup and restore.
- Public demo on sample data, README and architecture diagrams, release 1.0.0.

## Out of scope

- Horizontal scaling and more than one api process.
- A hosted service.
- New features.

## Prerequisites

- Phases 13 to 20.

## Deliverables

```text
infra/clickhouse/changes/            # conversation tables without the 90-day expiry
apps/api/app/api/limits.py           # concurrent-question and per-user limits
jobs/backup.py, jobs/restore.py      # consistent copy of ClickHouse data and the app state
docs/security.md                     # threat model, what each mode protects, hardening checklist
docs/operations.md                   # backup, restore, upgrade, moving to an external ClickHouse
.github/workflows/demo.yml           # builds the sample-data web app and publishes it
docs/architecture/                   # diagrams redrawn for v4
```

## Tasks

1. **Retention (test first).** Conversations, their messages, groups and feedback are kept until the user deletes them; run logs, events, LLM calls, SQL runs, audit and screening keep the 90-day expiry. A schema change removes the TTL from the conversation tables on existing volumes. Deleting a conversation in team mode still only hides it; individual mode gains a permanent delete.
2. **Concurrency (test first).** Keep one api process and say so. Add a cap on questions answered at once (the rest wait in order, with a status event) and keep the per-user rate limit; cap concurrent ClickHouse queries per role through the settings profile. A sync, a compile and an eval never run at the same time as each other.
3. **Load measurement.** With the LLM replaced by a fake of fixed latency, answer 1, 5 and 20 questions at once against a development dataset under the 8 GB reference limit; record median and 95th-percentile time per node and peak memory in `docs/operations.md`. Fix what the measurement shows to be the first bottleneck; do not optimise by guess.
4. **Secrets and logs (test first).** A test fails if any provider key, source password, session id or secret key appears in a log line, a trace payload, an `llm_calls` row or an API response. Error responses from providers and sources are reduced to fixed reasons.
5. **Web security.** Content-Security-Policy without inline script, `X-Content-Type-Options`, `Referrer-Policy`, frame denial; cookie flags of Phase 15 verified in a browser test; upload endpoints checked for size, type and path handling; the Host and Origin checks covered by tests for DNS-rebinding and cross-site requests.
6. **Supply chain.** Base images and binaries pinned by digest; Python and Node dependencies installed from lock files with hashes; every GitHub Action pinned by commit; the release attaches an SBOM and a provenance attestation; `SECURITY.md` states how to report a vulnerability and which versions get fixes. Dependency updates stay manual and reviewed.
7. **Backup and restore.** `fitcher backup` writes one archive of a ClickHouse `BACKUP` and a SQLite online backup taken together under a lock; `fitcher restore` restores into an empty data directory and refuses a non-empty one. The secret key is in the archive only when asked, with a warning. Tested by restoring into a second container and answering a question.
8. **Security review.** Run the repository's security review on the whole diff since Phase 12 and an independent pass over `docs/security.md`'s threat model: unauthenticated individual mode, a malicious web page, a malicious document or column value, a hostile source database, a stolen data volume, a compromised dependency. Every finding is fixed or recorded with its reason.
9. **Demo.** Build the web app with every feature on the hand-written sample data and no backend, mark it clearly as a demo, and publish it from a workflow. The release image contains no sample pack; the repository's development packs stay.
10. **Documentation.** README: what fitcher is, the one command, a screenshot of the setup, links to install, operations and security. Redraw the architecture diagrams for v4 with `scripts/build_architecture_diagram.py`. Remove the remaining "lab" wording from tracked files.
11. **Release.** Tag `v1.0.0`, move the Unreleased changelog entries under it, publish the image and the release notes.

## Contracts

- `docker exec fitcher fitcher backup --output /data/backups/<name>` and `fitcher restore --input <archive>`.
- Settings group `limits` with `concurrent_questions`.
- Supported upgrade path: any released version to the next minor version.

## Verification

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web ci && npm --prefix apps/web run typecheck && npm --prefix apps/web run test && npm --prefix apps/web run build
docker build -t fitcher:rc . && docker run -d --name fitcher-rc -p 127.0.0.1:3900:3000 -v fitcher-rc:/data fitcher:rc
docker exec fitcher-rc fitcher backup --output /data/backups/rc
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
python scripts/check_repository.py
```

## Definition of done

- A conversation older than 90 days is still readable; a run log of that age is gone.
- The load measurement is recorded and its first bottleneck fixed or explained.
- A backup restored into a new container answers a question with the same history.
- The security review has no open finding without a recorded reason.
- `v1.0.0` is published, the README's one command works on a clean machine, and the demo is reachable.

## Risks and open questions

- ClickHouse `BACKUP` of a large data directory doubles disk use for a while. Default: document it and allow a backup of the app state and packs alone.
- A strict Content-Security-Policy can break the chart library. Default: test charts and exports under the policy before enabling it.
- Where the demo is hosted is the owner's choice. Default: the repository's GitHub Pages.

## Branch and PR split

One branch per task group: `fix/db/keep-conversations-until-deleted`, `feat/api/limit-concurrent-questions`, `fix/api/keep-secrets-out-of-logs`, `feat/infra/back-up-and-restore-an-instance`, `chore/web/publish-sample-data-demo`, `chore/common/prepare-first-release`.
