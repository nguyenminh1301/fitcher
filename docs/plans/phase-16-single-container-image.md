# Phase 16: One image, one container

## Goal

Ship fitcher as one image that starts with one command and shows as one container: web, api and an embedded ClickHouse supervised together, one data volume, one published port, a low-memory profile for an 8 GB laptop, and a release workflow that publishes the image (DECISIONS §3).

## Scope

- The release image and its process supervision.
- First-start initialization: data directory, generated passwords and secret key, schema changes.
- Low-memory ClickHouse profile.
- Release workflow, image scan, install documentation.
- Qdrant as an internal supervised process until Phase 20.

## Out of scope

- Removing Qdrant (Phase 20).
- Kubernetes manifests, a Helm chart, a native installer.
- Automatic image updates.

## Prerequisites

- Phases 13, 14 and 15: no Keycloak, no LiteLLM Proxy, settings in the app state, schema changes.

## Deliverables

```text
Dockerfile                           # release image: web build, api environment, ClickHouse and Qdrant binaries, s6-overlay
infra/image/s6-rc.d/                 # init-data (oneshot), clickhouse, migrate (oneshot), qdrant, api, web
infra/image/clickhouse/              # embedded server configuration and the low-memory profile
infra/image/healthcheck.sh           # passes only when web, api and ClickHouse answer
deploy/compose.external-clickhouse.yaml
.github/workflows/release.yml        # multi-architecture build and push on a version tag
docs/install.md                      # the command, the data volume, upgrades, local models, external ClickHouse
```

## Tasks

1. **Image.** One multi-stage Dockerfile. ClickHouse and Qdrant binaries are copied from their official images at the versions pinned in `compose.yaml`; s6-overlay is verified by checksum; base images are pinned by digest. The Python environment installs without the `jobs` extras that only development needs (dbt), and no development pack, dataset or fixture is copied in.
2. **Supervision.** s6-overlay services in dependency order: `init-data`, `clickhouse`, `migrate`, `qdrant`, `api`, `web`. Every long-running service runs as the non-root application user. A service that keeps failing stops the container with a non-zero code; `SIGTERM` stops ClickHouse cleanly before exit.
3. **First start (test first where code allows).** `init-data` creates the layout under `/data`, generates the secret key and the ClickHouse user passwords once (mode 0600) and renders the ClickHouse user files from them. `migrate` runs `jobs.migrate` with the ClickHouse admin user; `api` never holds that user's password.
4. **Embedded or external ClickHouse.** With `CLICKHOUSE_URL` set, the `clickhouse` service is skipped and `migrate` and `api` use the external server; `deploy/compose.external-clickhouse.yaml` shows it.
5. **Low-memory profile.** Size the server memory cap from the container's cgroup limit (a fraction of it, with a floor); lower the mark cache; disable `metric_log`, `asynchronous_metric_log`, `trace_log` and `text_log`; let `GROUP BY` and `ORDER BY` spill to disk; cap query threads. Keep the per-role query limits of the compiled pack below the server cap.
6. **Ports.** Only `web` listens on the published port. `api`, ClickHouse and Qdrant listen on loopback inside the container. The documented command publishes on `127.0.0.1`.
7. **Healthcheck.** The image `HEALTHCHECK` runs `healthcheck.sh`; `docker ps` shows `healthy` only when a question could be answered.
8. **Measure.** On a clean machine record the compressed and unpacked image size, idle memory, memory while answering the acceptance question on a development dataset, and time from `docker run` to the setup page. Run once with `--memory 4g`. The numbers go into `docs/install.md`.
9. **Upgrade test.** Start the previous commit's image on a volume, stop it, start the new image on the same volume: data, settings and conversations are intact and the schema version advanced.
10. **Release workflow.** On a `v*` tag: build `linux/amd64` and `linux/arm64`, push to the registry with the version and `latest` tags, attach an SBOM and provenance attestation, scan the image with the existing gate. Actions are pinned by commit.
11. **Development Compose.** `compose.yaml` keeps `api`, `web`, `clickhouse`, `qdrant` and the fixture profiles for development. The README's Quick start becomes the one command; the development setup moves to CONTRIBUTING.md.

## Contracts

- Image `ghcr.io/nguyenminh1301/fitcher`; volume `/data`; port 3000.
- Environment: `CLICKHOUSE_URL`, `FITCHER_SECRET_KEY`, `FITCHER_ALLOWED_HOSTS`, `FITCHER_DATA_DIR`.
- `docker exec fitcher fitcher <job> [args]` runs a job module.

## Verification

```bash
docker build -t fitcher:dev .
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-test:/data fitcher:dev
docker ps --filter name=fitcher            # one container, healthy
docker exec fitcher fitcher migrate        # applies nothing
docker compose config --quiet && docker compose up --build --wait
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
```

Never delete an existing volume to make a step pass; use a new volume name.

## Definition of done

- On a machine with only Docker, the one command leads to the setup page and, after entering a model key and connecting a development source, to an answered question.
- `docker ps` shows one container; killing the api process inside it is followed by a supervised restart; `docker stop` exits cleanly within the stop timeout.
- The acceptance question is answered under `--memory 4g`.
- A tagged commit publishes a multi-architecture image that passes the scan gate.

## Risks and open questions

- s6-overlay without root limits some features. Default: run it as the application user with a writable `/run`; if that fails, start as root only to fix volume ownership and drop privileges for every service.
- The ClickHouse binary is about 760 MB unpacked. Default: accept it and report the size; do not strip it.
- `host.docker.internal` does not exist on Linux by default. Default: the documented Linux command adds `--add-host=host.docker.internal:host-gateway`.
- Registry name and visibility belong to the owner. Default: the repository's own GitHub Container Registry, public.

## Branch and PR split

`feat/infra/build-single-image` (Dockerfile, supervision, first start, profile, healthcheck), `chore/ci/publish-release-image` (workflow, scan), `chore/common/document-one-command-install` (install guide, README, Compose clean-up).
