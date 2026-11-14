# Install fitcher

fitcher ships as one image (DECISIONS §3). One container runs the web app, the API, an embedded ClickHouse server and the search index, supervised together; everything that must survive lives in one volume.

## Start

You need Docker and about 4 GB of memory for the container.

```bash
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-data:/data ghcr.io/nguyenminh1301/fitcher
```

On Linux, add `--add-host=host.docker.internal:host-gateway` if a model server runs on the same machine (see [Local models](#local-models)).

Open [localhost:3000](http://localhost:3000). The setup asks who uses the instance (only you, or a team that signs in) and which models to use. `docker ps` shows the container as `healthy` once the web app, the API and ClickHouse all answer.

The command publishes the app on the local machine only. To use another host port, change the first number: `-p 127.0.0.1:8080:3000`.

## Data volume

`/data` holds every persistent file:

| Path | Contents |
| --- | --- |
| `app.db` | Settings, accounts, model providers and stored secrets (encrypted) |
| `secret.key` | The key that encrypts the stored secrets, generated on the first start |
| `secrets/` | Generated ClickHouse passwords and the environment of the services (mode 0700) |
| `clickhouse/` | ClickHouse data, including conversations and run logs |
| `qdrant/` | The search index |
| `packs/`, `compiled/` | Domain Packs and their compiled form |
| `documents/` | Uploaded company documents |
| `models/` | Downloaded local models |

Back up an instance by stopping it and copying the volume:

```bash
docker stop fitcher
docker run --rm -v fitcher-data:/data:ro -v "$PWD":/backup debian:trixie-slim tar -czf /backup/fitcher-data.tar.gz -C /data .
docker start fitcher
```

Keep `secret.key` with the backup, or supply the key yourself as `FITCHER_SECRET_KEY` (base64 of 32 bytes): without it the stored provider keys cannot be read.

## Settings

The application keeps its settings in `app.db`; these environment variables set what the container needs before it starts:

| Variable | Meaning |
| --- | --- |
| `FITCHER_SECRET_KEY` | The instance key instead of a generated `secret.key` |
| `FITCHER_ALLOWED_HOSTS` | Comma-separated host names under which others reach the instance, for example behind a reverse proxy; without it only the local machine is answered |
| `CLICKHOUSE_URL` | An external ClickHouse server instead of the embedded one (see below) |
| `FITCHER_DATA_DIR` | The data directory inside the container (default `/data`) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_URL` | Create that model provider on the first start that finds none; afterwards providers are managed on the Models page |

The embedded ClickHouse sizes itself from the container's memory limit (`--memory`): the server takes half of it (at least 768 MiB) and one query at most half of the server's share, and large sorts and aggregations spill to disk.

## Upgrades

Pull the new image and start it on the same volume:

```bash
docker pull ghcr.io/nguyenminh1301/fitcher
docker stop fitcher
docker rm fitcher
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-data:/data ghcr.io/nguyenminh1301/fitcher
```

Every start applies the pending schema changes to the app state and to ClickHouse and records them, so a newer image upgrades the volume in place. An older image refuses to start on a volume a newer one has written; back up before upgrading if you may need to go back.

## Jobs

The job modules run inside the container with the ClickHouse administrator's credentials, which the long-running API never holds:

```bash
docker exec fitcher fitcher migrate
docker exec fitcher fitcher compile_pack --pack <name>
```

`docker exec fitcher fitcher` lists the jobs. A pack is read from `/data/packs/<name>`.

## Local models

A model server on the host (Ollama, LM Studio or any OpenAI-compatible endpoint) is reached as `host.docker.internal`, for example `http://host.docker.internal:11434` for Ollama. Docker Desktop provides that name; on Linux add `--add-host=host.docker.internal:host-gateway` to the `docker run` command.

## External ClickHouse

With `CLICKHOUSE_URL=http://<host>[:<port>]` (the HTTP interface) the embedded server does not start and the schema changes and the API use that server. It needs the fitcher users of [infra/clickhouse/users.d](../infra/clickhouse/users.d) with the passwords given to the container as `CLICKHOUSE_*_PASSWORD`, and an administrator in `CLICKHOUSE_ADMIN_USER` and `CLICKHOUSE_ADMIN_PASSWORD`. [deploy/compose.external-clickhouse.yaml](../deploy/compose.external-clickhouse.yaml) shows the layout:

```bash
docker compose -f deploy/compose.external-clickhouse.yaml --env-file deploy/.env up -d --wait
```

Only `http://` is accepted for now.

## Logs and restarts

`docker logs fitcher` shows every process. A process that exits is restarted; one that exits five times within a minute stops the container with its exit code. `docker stop` shuts ClickHouse down cleanly within Docker's default stop timeout.

## Measurements

Measured on 2026-11-14 on a linux/amd64 machine with 16 CPUs and 15 GB of memory, Docker 29.9.3, with the image built from commit `3fab159`:

| Measure | Value |
| --- | --- |
| Image, unpacked | 2.20 GB (the ClickHouse binary alone is about 0.8 GB) |
| Image, compressed (`docker save` with gzip) | 0.52 GB |
| Memory at idle, no limit | 357 MiB |
| Memory at idle, `--memory 4g` | 356 MiB (ClickHouse capped at 2 GiB, one query at 1 GiB) |
| `docker run` to the setup page answering | 2.8 s |
| `docker run` to `healthy` | 11 s (healthcheck every 10 s) |
| `docker stop` | 2 s |

Memory while answering a question has not been measured yet; it needs a connected source and a published pack.
