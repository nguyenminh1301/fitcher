# Operating fitcher

This guide covers backup and restore, upgrades, an external ClickHouse, the limits of the one api process and what was measured under load. [install.md](install.md) covers the first start and the settings; [security.md](security.md) covers the threat model.

## Retention

Conversations, their messages, groups and feedback have no expiry: they stay until their owner deletes them. Run logs, events, LLM calls, SQL runs, audit rows and screening results expire after 90 days. In individual mode a deleted conversation is removed for good with its messages and the feedback on its answers; in team mode it is only hidden from its owner, and an admin can still read it in the console.

## Backup

```bash
docker exec fitcher fitcher backup --output /data/backups/2026-11-17
docker cp fitcher:/data/backups/2026-11-17.tar.gz .
```

The archive holds a ClickHouse `BACKUP` of every fitcher database and of the pack role users, roles and settings profiles created with SQL, an online copy of `app.db`, the packs, compiled packs, documents, uploaded files and the generated ClickHouse passwords. Both copies are taken while no source sync, pack compile or eval run is in progress, and the instance keeps answering questions meanwhile. The archive is written with mode 0600.

| Option | Effect |
| --- | --- |
| `--app-only` | Leaves the ClickHouse data out. Use it when the disk cannot hold a second copy of the ClickHouse data for the duration of the backup, or with an external ClickHouse, which keeps its own backups. |
| `--include-secret-key` | Adds `secret.key`, which decrypts the stored provider keys and source passwords. Whoever holds such an archive can read them; keep it as safe as the volume. |

The ClickHouse copy is first written under `/data/backups/clickhouse/` and removed once it is in the archive, so a backup needs free space for about twice the compressed ClickHouse data while it runs.

## Restore

Restore into a new, empty volume before its first start, then start the instance on it:

```bash
docker run --rm --entrypoint fitcher -v fitcher-restored:/data -v "$PWD":/backups:ro \
  ghcr.io/nguyenminh1301/fitcher restore --input /backups/2026-11-17.tar.gz
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-restored:/data ghcr.io/nguyenminh1301/fitcher
```

`fitcher restore` refuses a volume that holds anything other than `backups/`, so two instances are never mixed. The files are restored at once; the ClickHouse data is restored by the first start, after ClickHouse answers and before the schema changes newer than the backup are applied. Without `secret.key` in the archive the stored secrets are removed, and provider keys and source passwords are entered again in the console.

This path was checked on the release image twice. A conversation written 200 days earlier was backed up from one container, restored into a second one, listed by `GET /api/conversations` there, and then deleted for good. An instance with an instant pack, its role user and a two-turn conversation answered by an OpenRouter model was backed up with `--include-secret-key` and restored into a new volume; the restored instance answered a third question of that conversation that needed the earlier turns ("Which month of that year was highest?"). Downloaded models are not in the archive, so the first question after a restore that uses local embeddings waits for the model to download again.

## Upgrade

Back up, pull the new image and start it on the same volume:

```bash
docker exec fitcher fitcher backup --output /data/backups/before-upgrade
docker pull ghcr.io/nguyenminh1301/fitcher
docker stop fitcher && docker rm fitcher
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-data:/data ghcr.io/nguyenminh1301/fitcher
```

Every start applies the pending schema changes to the app state and to ClickHouse. The supported upgrade path is from any released version to the next minor version; to skip versions, upgrade through each minor version in turn. An older image refuses a volume a newer one has written; restore the backup taken before the upgrade to go back.

## External ClickHouse

With `CLICKHOUSE_URL` the embedded ClickHouse does not start (see [install.md](install.md#external-clickhouse)). Moving an instance to an external server:

1. Take a backup with `fitcher backup` while the embedded server still runs.
2. Restore the archive's `clickhouse/<name>.zip` on the external server with `RESTORE ALL FROM File(...)`, from a path in its `backups.allowed_path`.
3. Create the fitcher users of `infra/clickhouse/users.d` there with the passwords of the archive's `secrets/clickhouse.env`.
4. Start the image with `CLICKHOUSE_URL` and the same passwords. From then on, back up ClickHouse on that server and the instance with `--app-only`.

## Limits

fitcher runs one api process; it does not scale to several.

| Limit | Default | Where |
| --- | --- | --- |
| Questions answered at once | 4 | `GET`/`PUT /settings/limits` (`concurrent_questions`, 1 to 64), admin only |
| Questions per user | `RATE_LIMIT_PER_MINUTE` | Environment |
| Concurrent ClickHouse queries of one pack role | 8 | The pack's settings profile (`max_concurrent_queries_for_user`) |
| Source syncs, pack compiles, eval runs and backups | One at a time | They wait for each other |

A question beyond the limit waits in arrival order; the chat shows "Waiting for a free slot" until it starts. A question whose browser leaves gives up its place.

## Load measurement

`scripts/measure_question_load.py` streams questions through the api's `event_stream` and question gate as `POST /ask` does, with the graph replaced by nodes that sleep a fixed time: 1 s on the two nodes that call a model before the query (extract, generate SQL) and 20 ms on the others. It measures the api's queueing, threads and streaming, not a model or ClickHouse.

Run on 2026-11-17 on a 16-CPU development machine, `limits.concurrent_questions = 4`:

| Questions at once | Median time | 95th percentile | Median wait for a place | Model node | Other node | Peak memory |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2.12 s | 2.12 s | 0 s | 1.00 s | 0.02 s | 186 MiB |
| 5 | 2.12 s | 4.24 s | 0 s | 1.00 s | 0.02 s | 186 MiB |
| 20 | 6.37 s | 10.61 s | 4.24 s | 1.00 s | 0.02 s | 186 MiB |

With `concurrent_questions = 20` all 20 questions finished in 2.13 s, so the time above 2.12 s is the configured queue and nothing else.

The first bottleneck the measurement showed was the thread pool: each question ran on the event loop's default executor, which holds `min(32, CPUs + 4)` threads, so on a 2-CPU host only 6 questions could run or wait for a place at once and the rest waited unseen and unordered. Questions now run on a pool of their own of 128 threads.

Not measured: the same load against a development dataset in ClickHouse under the 8 GB reference limit. A real run needs a compiled pack and an LLM replaced inside the release image; until it is recorded here, the concurrent-query cap of 8 per role and the question limit of 4 keep ClickHouse below its memory profile's assumptions.
