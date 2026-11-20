# Install fitcher

fitcher ships as one image (DECISIONS §3). One container runs the web app, the API, an embedded ClickHouse server and the search index, supervised together; everything that must survive lives in one volume.

## Start

You need Docker and about 4 GB of memory for the container.

```bash
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-data:/data ghcr.io/nguyenminh1301/fitcher
```

On Linux, add `--add-host=host.docker.internal:host-gateway` if a model server runs on the same machine (see [Local models](#local-models)).

Open [localhost:3000](http://localhost:3000). The setup asks which models to use and which data to connect; company documents are turned on later on the Documents page. `docker ps` shows the container as `healthy` once the web app, the API and ClickHouse all answer.

The command publishes the app on the local machine only. To use another host port, change the first number: `-p 127.0.0.1:8080:3000`.

## Data volume

`/data` holds every persistent file:

| Path | Contents |
| --- | --- |
| `app.db` | Settings, accounts, model providers and stored secrets (encrypted) |
| `secret.key` | The key that encrypts the stored secrets, generated on the first start |
| `secrets/` | Generated ClickHouse passwords and the environment of the services (mode 0700) |
| `clickhouse/` | ClickHouse data, including conversations and run logs |
| `packs/`, `compiled/` | Domain Packs and their compiled form |
| `documents/` | Uploaded company documents |
| `models/` | Downloaded local models |

The volume belongs to the `app` user (uid 10001), which runs the api, ClickHouse and the jobs; every start makes `/data` mode 0700. The web server runs as `web` (uid 10002), which reads nothing under `/data`. A bind-mounted directory must be writable by uid 10001; one owned by root is given to it on the first start.

Back up a running instance with `fitcher backup` and restore it into a new volume with `fitcher restore`; [operations.md](operations.md) shows both. Without the secret key in the backup, provider keys and source passwords are entered again after a restore.

## Settings

The application keeps its settings in `app.db`; these environment variables set what the container needs before it starts:

| Variable | Meaning |
| --- | --- |
| `FITCHER_SECRET_KEY` | The instance key instead of a generated `secret.key` |
| `FITCHER_ALLOWED_HOSTS` | Comma-separated host names under which others reach the instance, for example behind a reverse proxy; without it only the local machine is answered. A listed name answers only once an owner password is set on the Security page, and then only to a signed-in browser |
| `FITCHER_TRUSTED_PEERS` | Comma-separated addresses or networks (`10.0.2.0/24`) whose connections count as this machine. Only needed when a container runtime (rootless Docker, Podman) delivers the browser's connections from an address that is neither loopback nor the container's default gateway; the refusal names the address it saw |
| `FITCHER_TRUSTED_PROXIES` | Comma-separated addresses or networks of the reverse proxies in front of the instance, as the container sees them (usually the container's default gateway, such as `172.17.0.1`). Their `X-Forwarded-For` then names the client the sign-in throttle counts, so one visitor's wrong passwords do not hold back the others; without it every visitor behind the proxy shares one count. The owner at this computer is always counted apart |
| `CLICKHOUSE_URL` | An external ClickHouse server instead of the embedded one (see below) |
| `FITCHER_DATA_DIR` | The data directory inside the container (default `/data`) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_URL` | Create that model provider on the first start that finds none; afterwards providers are managed on the Models page |

The embedded ClickHouse sizes itself from the container's memory limit (`--memory`): the server takes half of it (at least 768 MiB) and one query at most half of the server's share, and large sorts and aggregations spill to disk.

## Reaching fitcher from other machines

Without further setup fitcher answers only the computer it runs on. To open it from elsewhere, put an HTTPS reverse proxy or a tunnel in front of the published port, in this order:

1. Start fitcher with the public name listed, still published on loopback: `-e FITCHER_ALLOWED_HOSTS=fitcher.example.com` and, so that one visitor's wrong passwords do not slow down the others, `-e FITCHER_TRUSTED_PROXIES=172.17.0.1` (the address the proxy's connections arrive from: for a proxy on the host, the gateway of the container's network, which `docker network inspect bridge` shows).
2. Open [localhost:3000](http://localhost:3000) on this computer and set the owner password on the Security page. Until it is set, fitcher refuses every request through the public name.
3. Start the proxy. It must send the public name as `Host`: a proxy that sends `127.0.0.1` or `localhost` instead is refused, and the page says so.

Serve the name on the standard HTTPS port. The browser's `Origin` and the forwarded `Host` must match, and nginx's `$host` leaves out a port.

**nginx** (uploads up to 256 MiB, answers streamed as they are written):

```nginx
server {
    listen 443 ssl;
    server_name fitcher.example.com;
    # ssl_certificate and ssl_certificate_key as for any other site
    client_max_body_size 300m;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

**Caddy** keeps the `Host`, sets the forwarding headers, streams answers and gets the certificate by itself:

```caddyfile
fitcher.example.com {
	request_body {
		max_size 300MB
	}
	reverse_proxy 127.0.0.1:3000
}
```

**Cloudflare Tunnel** (`cloudflared`) with a named tunnel and the public hostname `fitcher.example.com`:

```yaml
tunnel: <tunnel id>
credentials-file: /etc/cloudflared/<tunnel id>.json
ingress:
  - hostname: fitcher.example.com
    service: http://127.0.0.1:3000
  - service: http_status:404
```

Do not set `httpHostHeader`: cloudflared then sends the public hostname, as fitcher needs. Cloudflare's own upload limit (100 MB on the free plan) caps uploads through the tunnel.

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

On Linux, Ollama listens on `127.0.0.1` only by default, which the container cannot reach. Start it with `OLLAMA_HOST=0.0.0.0`; for the system service, run `sudo systemctl edit ollama`, add `Environment="OLLAMA_HOST=0.0.0.0"` under `[Service]` and restart it. Adding an Ollama provider asks the server for its installed models first: the tiers are proposed from those models, and a server that does not answer or has no chat model installed is not added.

## Data sources

The setup's Data step and the Sources page connect to a database by host name. The container reaches the same addresses the machine does, with three cases to know:

- **A database on the internet or the local network** is reached by its usual host name or IP address. Choose the TLS mode the server requires.
- **A database installed on this computer** is reached as `host.docker.internal`, with the same `--add-host=host.docker.internal:host-gateway` on Linux as for [local models](#local-models). PostgreSQL and MySQL often listen on `127.0.0.1` only: make the server listen on an address the container can reach (`listen_addresses` in PostgreSQL, `bind-address` in MySQL) and allow the Docker bridge network, usually `172.17.0.0/16`, in its access rules (`pg_hba.conf` in PostgreSQL).
- **A database in another Docker container** is reached by its container name only when both containers share a Docker network; the default network does not resolve names. Find the database's network with `docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' <database-container>`, then join fitcher to it and use the container name as the host:

```bash
docker network connect <network> fitcher
```

`docker network connect` lasts until the container is removed; to keep it across an upgrade, add `--network <network>` to the `docker run` command instead. Alternatively, publish the database's port on the host and connect to `host.docker.internal` as above.

## External ClickHouse

With `CLICKHOUSE_URL=http://<host>[:<port>]` (the HTTP interface) the embedded server does not start and the schema changes and the API use that server. It needs the fitcher users of [infra/clickhouse/users.d](../infra/clickhouse/users.d) with the passwords given to the container as `CLICKHOUSE_*_PASSWORD`, and an administrator in `CLICKHOUSE_ADMIN_USER` and `CLICKHOUSE_ADMIN_PASSWORD`. [deploy/compose.external-clickhouse.yaml](../deploy/compose.external-clickhouse.yaml) shows the layout:

```bash
docker compose -f deploy/compose.external-clickhouse.yaml --env-file deploy/.env up -d --wait
```

Only `http://` is accepted for now.

## Logs and restarts

`docker logs fitcher` shows every process. A process that exits is restarted; one that exits five times within a minute stops the container with its exit code. `docker stop` shuts ClickHouse down cleanly within Docker's default stop timeout.

## Measurements

Measured on 2026-11-16 on a linux/amd64 machine with 16 CPUs and 15 GB of memory, Docker 29.9.3, with the image built after search moved into ClickHouse and Qdrant was removed (Phase 20); the container runs ClickHouse, the api and the web server only:

| Measure | Value |
| --- | --- |
| Image, unpacked | 2.35 GB (the ClickHouse binary alone is about 0.8 GB); 2.48 GB with Qdrant before Phase 20 |
| Image, compressed (`docker save` with gzip) | 0.54 GB |
| Memory at idle, no limit | 308 MiB |
| Memory at idle, `--memory 4g` | 356 MiB with Qdrant (Phase 16); ClickHouse capped at 2 GiB, one query at 1 GiB |
| `docker run` to the setup page answering | 3.3 s |
| `docker run` to `healthy` | 11 s (healthcheck every 10 s) |
| `docker stop` | 2 s |

Memory while answering a question has not been measured yet; it needs a connected source and a published pack.
